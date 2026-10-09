"""Never spend Claude extra usage or ChatGPT credits: only the subscription's included usage.

Both providers report usage while Flippy talks to them:

  Claude (Agent SDK RateLimitEvent): status allowed / allowed_warning / rejected, utilization 0-1 of the window,
    rate_limit_type ("overage" = the request is running on extra usage), overage_status
  Codex (app-server account/rateLimits/read, and account/rateLimits/updated mid-request): ordinaryUsageAllowed
    (included usage left, checked against the account), usedPercent per window, rateLimitReachedType,
    spendControlReached

The same rules for both:
  - before a request: refuse once included usage is used up, a window is STOP_AT or more used, or the last report
    showed extra usage / credits
  - during a request: stop it the moment the provider reports extra usage / credits or the limit reached
  - then refuse until the window resets, saying when

What this can't promise: Claude has no "check before sending", so the first request after Flippy starts relies on
what Claude reports during it; and a single request that crosses the limit midway could be billed for a sliver
before the report arrives. STOP_AT keeps requests from starting near the edge. The only absolute guarantee is
turning extra usage (Claude) and credits (ChatGPT) off in the account, which setup tells the user.
"""
import time

STOP_AT = 0.95          # don't start a request once a usage window is this full
UNKNOWN_RESET_S = 1800  # a block without a reset time from the provider is lifted after this long

PAID = {"claude": "extra usage", "codex": "ChatGPT credits"}
PLAN = {"claude": "Claude", "codex": "ChatGPT"}


class PlanLimitReached(Exception):
    """A request refused or stopped so it can't run on paid usage. str() is the message for the user."""


class Guard:
    def __init__(self, provider, clock=time.time):
        self.provider = provider
        self.clock = clock
        self.until = None       # unix time the block lifts (None = until the provider says otherwise)
        self.blocked = False
        self.why = ""

    # ---- the rule everyone calls
    def check(self):
        """Raise PlanLimitReached if a request now could run on paid usage."""
        if self.blocked and self.until is not None and self.clock() >= self.until:
            self.blocked, self.until, self.why = False, None, ""
        if self.blocked:
            raise PlanLimitReached(self.message())

    def message(self):
        when = ""
        if self.until:
            when = " It resets " + time.strftime("at %-I:%M %p" if self.until - self.clock() < 20 * 3600
                                                 else "on %a at %-I:%M %p", time.localtime(self.until)) + "."
        return (f"You've reached your {PLAN[self.provider]} plan's limit{(' (' + self.why + ')') if self.why else ''}. "
                f"Flippy stops here so it never uses {PAID[self.provider]}.{when}")

    def _block(self, why, until=None):
        self.blocked, self.why = True, why
        until = int(until) if until else int(self.clock()) + UNKNOWN_RESET_S
        self.until = max(self.until or 0, until)

    # ---- Claude: one RateLimitInfo per change (claude_agent_sdk.RateLimitInfo)
    def claude(self, info):
        """Feed a rate-limit report. True = stop the request in flight now."""
        kind, status, used = info.rate_limit_type, info.status, info.utilization
        if kind == "overage" or (status == "rejected" and info.overage_status in ("allowed", "allowed_warning")):
            self._block("extra usage would be used", info.resets_at)
            return True
        if status == "rejected":
            self._block("limit reached", info.resets_at)
            return True
        if used is not None and used >= STOP_AT:
            self._block(f"{round(used * 100)}% used", info.resets_at)  # this request may finish; no new ones
        return False

    # ---- Codex: a GetAccountRateLimitsResponse, or the rateLimits snapshot from account/rateLimits/updated
    def codex(self, report):
        """Feed a usage report. True = stop the request in flight now."""
        snapshots = []
        full = "rateLimits" in report or "rateLimitsByLimitId" in report
        if full:
            if report.get("ordinaryUsageAllowed") is False:
                self._block("included usage used up", _codex_reset(report.get("rateLimits") or {}))
                return True
            snapshots = [report.get("rateLimits") or {}] + list((report.get("rateLimitsByLimitId") or {}).values())
        else:
            snapshots = [report]
        stop = False
        for snap in snapshots:
            if not isinstance(snap, dict):
                continue
            reset = _codex_reset(snap)
            if snap.get("rateLimitReachedType") or snap.get("spendControlReached"):
                self._block("limit reached", reset)
                stop = True
                continue
            for window in (snap.get("primary"), snap.get("secondary")):
                if isinstance(window, dict) and isinstance(window.get("usedPercent"), (int, float)):
                    used = window["usedPercent"] / 100
                    if used >= 1:
                        self._block("limit reached", window.get("resetsAt"))
                        stop = True
                    elif used >= STOP_AT:
                        self._block(f"{round(used * 100)}% used", window.get("resetsAt"))
        return stop

    def codex_read(self, report):
        """A fresh account/rateLimits/read before a request: block, or lift an earlier block if it's clean now."""
        before = (self.blocked, self.until)
        self.blocked, self.until, self.why = False, None, ""
        self.codex(report)
        if not self.blocked and report.get("ordinaryUsageAllowed") is None and before[0]:
            self.blocked, self.until = before  # nothing definite came back: keep what we knew


def _codex_reset(snap):
    resets = [w.get("resetsAt") for w in (snap.get("primary"), snap.get("secondary"))
              if isinstance(w, dict) and w.get("resetsAt")]
    return max(resets) if resets else None


GUARDS = {"claude": Guard("claude"), "codex": Guard("codex")}
