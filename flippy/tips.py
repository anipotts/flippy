"""Tips mode: Claude writes a deck of tips for an app once; Flippy deals them out locally.

One text-only call writes ~25 tips (beginner to advanced) for an app, cached in
~/.config/flippy/tips/<app>.json. Then the Dealer shows one now and then, in a calm
moment (you've been working, and just paused for a few seconds), using the same
samples as help mode (flippy/watch.py). No Claude per tip. Buttons on a tip:

  Got it     next one later
  Knew that  you're past this level: two of those at a level skips you ahead
  Show me    the one live call: a screenshot so Claude can point at it on your screen

When the deck runs low on tips at your level, one more call refills it (telling
Claude which ones you already have). Pure logic apart from the JSON file; see
tests/test_tips.py.
"""
import json
import os
import re
from collections import deque
from dataclasses import dataclass, field

from . import settings, watch

DIR = os.path.join(os.path.dirname(settings.PATH), "tips")
DECK_SIZE = 25
REFILL_SIZE = 15
REFILL_BELOW = 5            # refill when fewer unseen tips than this are left at their level
WARMUP_S = 60               # first tip at least this long after starting to watch an app
EVERY_S = 300               # then at most one tip per this long
CALM_IDLE = (3, 15)         # show it in a short pause: idle between these many seconds...
CALM_BUSY_EVENTS = 10       # ...after real activity in the minute before
KNEW_TO_SKIP = 2            # "Knew that" this many times at a level: move up a level


def _path(app):
    return os.path.join(DIR, re.sub(r"[^A-Za-z0-9._-]", "_", app) + ".json")


@dataclass
class Deck:
    app: str
    app_name: str
    goal: str = ""
    skill: int = 1
    tips: list = field(default_factory=list)   # [{"text", "level", "state": new|shown|knew}]

    @classmethod
    def load(cls, app):
        try:
            with open(_path(app)) as f:
                d = json.load(f)
            return cls(d["app"], d["app_name"], d.get("goal", ""), int(d.get("skill", 1)), list(d.get("tips", [])))
        except (OSError, ValueError, KeyError):
            return None

    def save(self):
        os.makedirs(DIR, exist_ok=True)
        tmp = _path(self.app) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.__dict__, f, indent=1)
        os.replace(tmp, _path(self.app))

    def add(self, new_tips):
        have = {t["text"] for t in self.tips}
        for t in new_tips:
            if t["text"] not in have:
                self.tips.append({"text": t["text"], "level": t["level"], "state": "new"})

    def _fresh(self):
        return [t for t in self.tips if t["state"] == "new"]

    def next_tip(self):
        """The easiest unseen tip at or above their level (else any unseen one), or None."""
        fresh = self._fresh()
        at_level = [t for t in fresh if t["level"] >= self.skill]
        pool = at_level or fresh
        return min(pool, key=lambda t: t["level"]) if pool else None

    def needs_refill(self):
        return len([t for t in self._fresh() if t["level"] >= self.skill]) < REFILL_BELOW

    def mark(self, tip, state):
        tip["state"] = state
        if state == "knew":
            knew = sum(1 for t in self.tips if t["state"] == "knew" and t["level"] == tip["level"])
            if knew >= KNEW_TO_SKIP and tip["level"] >= self.skill:
                self.skill = min(tip["level"] + 1, 3)

    def texts(self):
        return [t["text"] for t in self.tips]


@dataclass
class Dealer:
    """Feed it the same samples as watch.Watcher; it says when it's a good moment for a tip."""
    every_s: float = EVERY_S
    _app: str | None = None
    _since: float = 0.0
    _last_tip_t: float = -1e9
    _prev_events: int | None = None
    _activity: deque = field(default_factory=deque)

    def reset(self):
        self._app = None
        self._prev_events = None
        self._activity.clear()

    def shown(self, t):
        self._last_tip_t = t

    def feed(self, s: watch.Sample, apps, muted) -> bool:
        if s.app is None or s.app not in apps or s.app in muted:
            self.reset()
            return False
        if s.app != self._app:
            self.reset()
            self._app, self._since = s.app, s.t
        if s.events is not None and self._prev_events is not None:
            self._activity.append((s.t, max(s.events - self._prev_events, 0)))
        self._prev_events = s.events
        while self._activity and self._activity[0][0] < s.t - 60:
            self._activity.popleft()
        if s.t - self._since < WARMUP_S or s.t - self._last_tip_t < self.every_s:
            return False
        if s.idle_s is None or not (CALM_IDLE[0] <= s.idle_s <= CALM_IDLE[1]):
            return False
        return sum(n for _, n in self._activity) >= CALM_BUSY_EVENTS
