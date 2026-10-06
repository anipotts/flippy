"""Help mode: notice when someone seems stuck in an app they're learning, and offer a hand.

Deterministic on purpose: no Claude until the person presses "Help". The platform
samples a few cheap signals every couple of seconds (flippy/mac/sensors.py) and
this module turns them into at most one "need a hand?" offer at a time:

  stalled   busy for a while, then still: no input and an unchanging screen
            (but not so long that they've clearly walked away)
  circles   the screen keeps flipping between the same few states (opening and
            closing the same menus/panels) without anything new appearing
  dialog    a new, smaller window popped up in the middle of the app's window
            (usually an error or a question)

"Not now" makes it wait longer before asking again in that app (per-app backoff);
"Help" eases it back. Everything here is pure logic over Sample objects, so it
runs (and is tested) without any windows: see tests/test_watch.py.

Any signal a platform can't provide is None, and the rules that need it stay off.
"""
from collections import deque
from dataclasses import dataclass, field

SAMPLE_S = 2.0              # how often the platform samples

# stalled
BUSY_WINDOW_S = 60          # "busy" = this much input in the minute before going still
BUSY_EVENTS = 15
STALL_S = 25                # still for this long (x the app's backoff) = maybe stuck
AWAY_S = 180                # still for longer than this = walked away; don't ask
SCREEN_DIFF = 0.02          # mean thumbnail difference (0-1) that counts as "the screen changed"

# circles
CIRCLE_WINDOW_S = 45
CIRCLE_MIN_FLIPS = 6        # screen changes in the window...
CIRCLE_MAX_STATES = 3       # ...between at most this many distinct screens...
CIRCLE_MIN_EVENTS = 10      # ...while clicking around
STATE_MATCH = 0.03          # thumbnails closer than this are "the same screen"

# dialogs
DIALOG_MAX_AREA = 0.5       # new window at most this fraction of the app's main window...
DIALOG_CENTER = 0.2         # ...centered within this fraction of the main window's size

# pacing
COOLDOWN_S = 90             # after any offer, don't ask again for this long (any app)
BACKOFF_STEP = 1.5          # "Not now": thresholds in that app x this
BACKOFF_MAX = 4.0


@dataclass
class Sample:
    t: float                          # seconds (monotonic)
    app: str | None                   # frontmost app id (bundle id / app_id)
    app_name: str | None = None
    idle_s: float | None = None       # seconds since the last keyboard/mouse input
    events: int | None = None         # cumulative input event count (deltas are what matter)
    thumb: list | None = None         # small grayscale screenshot, values 0-1, fixed length
    windows: list | None = None       # [(window id, (x, y, w, h))] of the frontmost app, largest first


@dataclass
class Offer:
    app: str
    app_name: str
    reason: str                       # "stalled" | "circles" | "dialog"

    def headline(self):
        return f"Need a hand with {self.app_name}?"

    def detail(self):
        return {"stalled": "Looks like you paused for a bit.",
                "circles": "Looks like you're going back and forth.",
                "dialog": "Something popped up."}[self.reason]

    def question(self):
        """What to ask Claude when they press Help (with a screenshot)."""
        why = {"stalled": "I was working, then stopped. I think I'm stuck.",
               "circles": "I keep opening and closing the same things and can't find what I need.",
               "dialog": "A window just popped up and I'm not sure what to do with it."}[self.reason]
        return (f"I'm learning {self.app_name}. {why} Look at my screen, work out what I'm most likely "
                f"trying to do, and show me the next step.")


def thumb_diff(a, b):
    if a is None or b is None or len(a) != len(b) or not a:
        return 0.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


@dataclass
class _AppState:
    backoff: float = 1.0


@dataclass
class Watcher:
    """Feed it samples; it returns an Offer when it's time to ask."""
    apps: set = field(default_factory=set)        # app ids to watch
    muted: set = field(default_factory=set)       # "don't ask in this app"
    per_app: dict = field(default_factory=dict)
    last_offer_t: float = -1e9
    _app: str | None = None
    _prev: Sample | None = None
    _activity: deque = field(default_factory=deque)   # (t, input events since the previous sample)
    _last_change_t: float = 0.0
    _last_thumb: list | None = None
    _states: deque = field(default_factory=deque)     # (t, thumb) at each screen change
    _windows: set = field(default_factory=set)
    _stall_fired: bool = False

    def state(self, app):
        return self.per_app.setdefault(app, _AppState())

    def reset(self):
        self._app = self._prev = self._last_thumb = None
        self._activity.clear()
        self._states.clear()
        self._windows = set()
        self._stall_fired = False

    # ---- feedback from the person
    def not_now(self, app):
        st = self.state(app)
        st.backoff = min(st.backoff * BACKOFF_STEP, BACKOFF_MAX)

    def helped(self, app):
        st = self.state(app)
        st.backoff = max(st.backoff / BACKOFF_STEP, 1.0)

    def mute(self, app):
        self.muted.add(app)

    # ---- the loop
    def feed(self, s: Sample) -> Offer | None:
        if s.app is None or s.app not in self.apps or s.app in self.muted:
            self.reset()
            return None
        if s.app != self._app:  # switched apps: start fresh, but don't pounce right away
            self.reset()
            self._app = s.app
            self._last_change_t = s.t
            self._windows = {w[0] for w in (s.windows or [])}
            self._last_thumb = s.thumb
            self._prev = s
            return None
        prev, self._prev = self._prev, s

        # activity: input events per sample
        if s.events is not None and prev.events is not None:
            self._activity.append((s.t, max(s.events - prev.events, 0)))
        while self._activity and self._activity[0][0] < s.t - max(BUSY_WINDOW_S, CIRCLE_WINDOW_S) - AWAY_S:
            self._activity.popleft()

        # screen changes
        changed = False
        if s.thumb is not None:
            if self._last_thumb is None or thumb_diff(s.thumb, self._last_thumb) > SCREEN_DIFF:
                changed = self._last_thumb is not None
                self._last_thumb = s.thumb
                if changed:
                    self._last_change_t = s.t
                    self._states.append((s.t, s.thumb))
        while self._states and self._states[0][0] < s.t - CIRCLE_WINDOW_S:
            self._states.popleft()
        if (s.idle_s is not None and s.idle_s < SAMPLE_S) or changed:
            self._stall_fired = False  # they're doing something: a new stall can be offered later

        new_windows = self._new_windows(s)

        if s.t - self.last_offer_t < COOLDOWN_S:
            return None
        backoff = self.state(s.app).backoff
        reason = None
        if new_windows and self._is_dialog(s, new_windows):
            reason = "dialog"
        elif self._circling(s):
            reason = "circles"
        elif self._stalled(s, backoff):
            reason = "stalled"
        if reason is None:
            return None
        self.last_offer_t = s.t
        if reason == "stalled":
            self._stall_fired = True
        self._states.clear()
        return Offer(s.app, s.app_name or s.app, reason)

    # ---- rules
    def _events_between(self, t0, t1):
        return sum(n for t, n in self._activity if t0 < t <= t1)

    def _stalled(self, s, backoff):
        if self._stall_fired or s.idle_s is None:
            return False
        need = STALL_S * backoff
        if not (need <= s.idle_s <= AWAY_S):
            return False
        if s.thumb is not None and s.t - self._last_change_t < need:
            return False  # the screen is still moving (playback, a build...): not stuck
        went_still = s.t - s.idle_s
        return self._events_between(went_still - BUSY_WINDOW_S, went_still) >= BUSY_EVENTS

    def _circling(self, s):
        if len(self._states) < CIRCLE_MIN_FLIPS or s.events is None:
            return False
        distinct = []
        for _, th in self._states:
            if not any(thumb_diff(th, d) < STATE_MATCH for d in distinct):
                distinct.append(th)
                if len(distinct) > CIRCLE_MAX_STATES:
                    return False
        return self._events_between(s.t - CIRCLE_WINDOW_S, s.t) >= CIRCLE_MIN_EVENTS

    def _new_windows(self, s):
        if s.windows is None:
            return []
        ids = {w[0] for w in s.windows}
        new = [w for w in s.windows if w[0] not in self._windows]
        self._windows = ids
        return new

    @staticmethod
    def _is_dialog(s, new_windows):
        main = max((w for w in s.windows if w not in new_windows), key=lambda w: w[1][2] * w[1][3], default=None)
        if main is None:
            return False
        mx, my, mw, mh = main[1]
        for _, (x, y, w, h) in new_windows:
            if w * h > DIALOG_MAX_AREA * mw * mh or w < 120 or h < 60:
                continue  # too big for a dialog, or a tooltip/popover sliver
            if (abs((x + w / 2) - (mx + mw / 2)) <= DIALOG_CENTER * mw
                    and abs((y + h / 2) - (my + mh / 2)) <= DIALOG_CENTER * mh):
                return True
        return False
