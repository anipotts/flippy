"""What a failure says: one short, general sentence and a readable code, e.g. "Claude couldn't answer. · CLAUDE-FAILED".

Every code is documented in docs/errors.md (what happened, what to do). Codes are permanent: a retired code is
never reused for something else. The log gets the code plus the error's first line, never the user's question.

Errors carry their kind from where they start: Claude's reply error (claude_agent_sdk.AssistantMessageError) and
SDK exception types, CodexError.code, ProviderChoiceRequired.kind, PlanLimitReached. Text is only sniffed as a last
resort for Claude results that come back as plain text.
"""
import asyncio

CODES = {
    # connecting
    "CLAUDE-LOGIN": "Claude Code isn't logged in. Log in from Setup.",
    "CODEX-LOGIN": "ChatGPT isn't signed in. Sign in from Setup.",
    "NO-PROVIDER": "No subscription is connected. Connect one in Setup.",
    "PICK-PROVIDER": "Both subscriptions are connected. Pick one in Setup.",
    # Claude
    "CLAUDE-MISSING": "Claude Code isn't installed.",
    "CLAUDE-START": "Claude Code couldn't start.",
    "CLAUDE-BUSY": "Claude is having trouble right now. Try again in a minute.",
    "CLAUDE-RATE": "Claude is getting too many requests. Try again shortly.",
    "CLAUDE-BILLING": "Your Claude plan can't take this request.",
    "CLAUDE-REJECTED": "Claude couldn't accept this request.",
    "CLAUDE-INCOMPLETE": "Claude stopped before finishing.",
    "CLAUDE-FAILED": "Claude couldn't answer.",
    # Codex / ChatGPT
    "CODEX-MISSING": "Codex isn't installed.",
    "CODEX-OLD": "Codex needs an update.",
    "CODEX-START": "Codex couldn't start.",
    "CODEX-RUNTIME": "Codex couldn't start its private runtime.",
    "CODEX-ISOLATION": "Codex couldn't run separately from your other Codex settings.",
    "CODEX-DISCONNECTED": "Codex disconnected. Try again.",
    "CODEX-NO-RESPONSE": "Codex didn't respond. Try again.",
    "CODEX-INCOMPLETE": "Codex stopped before finishing.",
    "CODEX-FAILED": "Codex couldn't answer.",
    # plan limits (the usage guard: never extra usage or credits)
    "PLAN-LIMIT": "You've reached your plan's limit.",
    # desktop tasks (/act)
    "ACT-HELD": "A key or mouse button was held down, so Flippy didn't act.",
    "ACT-DECLINED": "Action declined.",
    "ACT-SCREEN-CHANGED": "The screen changed before Flippy could act.",
    "ACT-WINDOW-CHANGED": "The window Flippy was working in changed.",
    "ACT-CAPTURE": "Flippy couldn't see the screen.",
    "ACT-CLEANUP": "Flippy couldn't confirm it let go of the keyboard and mouse. Restart Flippy.",
    "ACT-PERMISSION": "Flippy needs Screen Recording and Accessibility permission.",
    "ACT-LIMIT": "The task reached its step limit.",
    "ACT-STOPPED": "The task stopped.",
    "ACT-FAILED": "The task couldn't finish.",
    # anything else
    "TIMEOUT": "The answer took too long. Try again.",
    "NETWORK": "Couldn't reach the model. Check your connection.",
    "UNKNOWN": "Something went wrong.",
}

# claude_agent_sdk.types.AssistantMessageError, plus Flippy's own "incomplete"
CLAUDE_KINDS = {"authentication_failed": "CLAUDE-LOGIN", "billing_error": "CLAUDE-BILLING",
                "rate_limit": "CLAUDE-RATE", "invalid_request": "CLAUDE-REJECTED",
                "server_error": "CLAUDE-BUSY", "unknown": "CLAUDE-FAILED", "incomplete": "CLAUDE-INCOMPLETE"}
PROVIDER_KINDS = {"claude-login": "CLAUDE-LOGIN", "codex-login": "CODEX-LOGIN", "none": "NO-PROVIDER",
                  "pick": "PICK-PROVIDER"}
# the act reason codes in Flippy._action_done
ACT_REASONS = {"input_held": "ACT-HELD", "declined": "ACT-DECLINED", "pixels_changed": "ACT-SCREEN-CHANGED",
               "target_changed": "ACT-WINDOW-CHANGED", "capture_failed": "ACT-CAPTURE",
               "cleanup_failed": "ACT-CLEANUP", "permission": "ACT-PERMISSION", "operation_failed": "ACT-STOPPED"}
LOGIN_CODES = ("CLAUDE-LOGIN", "CODEX-LOGIN", "NO-PROVIDER")


def code_of(err):
    """The code for an exception."""
    from .usage_guard import PlanLimitReached
    if isinstance(err, PlanLimitReached):
        return "PLAN-LIMIT"
    code = getattr(err, "code", None)  # CodexError
    if code in CODES:
        return code
    kind = getattr(err, "kind", None)  # BrainError (Claude), ProviderChoiceRequired
    if kind in PROVIDER_KINDS:
        return PROVIDER_KINDS[kind]
    if kind in CLAUDE_KINDS:
        return CLAUDE_KINDS[kind]
    if isinstance(err, (asyncio.TimeoutError, TimeoutError)):
        return "TIMEOUT"
    try:
        from claude_agent_sdk import ClaudeSDKError, CLIConnectionError, CLINotFoundError
    except ImportError:
        ClaudeSDKError = CLIConnectionError = CLINotFoundError = ()
    if CLINotFoundError and isinstance(err, CLINotFoundError):
        return "CLAUDE-MISSING"
    if CLIConnectionError and isinstance(err, CLIConnectionError):
        return "CLAUDE-START"
    if ClaudeSDKError and isinstance(err, ClaudeSDKError):
        return "CLAUDE-FAILED"
    from .brain import BrainError
    if isinstance(err, BrainError):  # a Claude result that came back as text only
        low = str(err).lower()
        if "401" in low or "authentication" in low or "not logged in" in low:
            return "CLAUDE-LOGIN"
        if "429" in low or "rate limit" in low or "rate_limit" in low:
            return "CLAUDE-RATE"
        if "overloaded" in low or "529" in low or " 500" in low or "server error" in low:
            return "CLAUDE-BUSY"
        return "CLAUDE-FAILED"
    if isinstance(err, (ConnectionError, OSError)):
        return "NETWORK"
    return "UNKNOWN"


def say(code, sentence=None):
    """What the user sees: the sentence, then the code to look up."""
    return f"{sentence or CODES[code]} · {code}"


def describe(err):
    """(what the user sees, what goes in the log) for an exception."""
    code = code_of(err)
    from .usage_guard import PlanLimitReached
    sentence = str(err) if isinstance(err, PlanLimitReached) else None  # it says when the limit resets
    first = (str(err).strip().splitlines() or [""])[0][:160]
    reason = getattr(err, "reason", None)  # CodexError: which check, by a fixed name
    return say(code, sentence), (f"{code}: {type(err).__name__}" + (f" ({reason})" if reason else "")
                                 + (f": {first}" if first else ""))
