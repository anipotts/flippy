"""Pure walkthrough state. The controller owns clocks, input watchers and rendering."""
import math
import re
from dataclasses import dataclass
from .point import segments

HOLD = {'slow': (3.5, .07), 'normal': (2.2, .045), 'fast': (1.2, .025)}

@dataclass(frozen=True)
class Options:
    speed: float = 1.0
    pace: str = 'normal'
    tutorial: bool = False
    clicks_available: bool = False
    wait_for_clicks: bool = True
    typing_available: bool = False
    pointer_size: float = 1.0
    show_seconds: float = 12.0
    max_show_seconds: float = 60.0

class Playback:
    def __init__(self, now):
        self.raw = ''; self.done = False; self.step = 0
        self.shown = 0.; self.typed_at = None; self.last = now
        self.pointed_step = -1; self.pointed = False
        self.paused = False; self.finished = False; self.waiting = False
        self.clicked_at = None; self.acted = set(); self.target = None
        self.stopped = False

    def append(self, delta):
        if not self.done and not self.stopped:
            self.raw += delta

    def finish(self, raw=None):
        if raw is not None: self.raw = raw
        self.done = True

    def known(self):
        return [s for s in segments(self.raw, self.done) if s.complete]

    def hold(self, seg, opts):
        minimum, per_char = HOLD.get(opts.pace, HOLD['normal'])
        return (minimum + per_char * len(seg.text)) / opts.speed

    def _continues(self, segs, opts):
        return bool(opts.tutorial and self.acted and max(self.acted) >=
                    max((i for i, s in enumerate(segs) if s.point), default=-1))

    def _acted(self, events):
        self.acted.add(self.step); self.waiting = False; self.clicked_at = None
        events.append(('watch_clicks', False))

    def stop(self):
        self.stopped = True
        events = [('watch_clicks', False)] if self.waiting else []
        self.waiting = False
        return events

    def click(self, x, y, now, opts):
        if self.waiting and self.target and self.clicked_at is None:
            if math.hypot(x-self.target[0], y-self.target[1]) <= 55 * opts.pointer_size ** .5:
                self.clicked_at = now
                return True
        return False

    def card(self, now, opts):
        known = self.known()
        if not known: return None
        step = min(self.step, len(known)-1); seg = known[step]
        frac = self.shown / max(len(seg.text), 1) * .5
        if self.typed_at is not None:
            frac += min(max(now-self.typed_at, 0)/self.hold(seg, opts), 1) * .5
        progress = (step+1)/len(known) if self.finished else (step+frac)/len(known)
        return dict(text=seg.text[:int(self.shown)] or ' ', header=seg.point.label if seg.point else None,
                    follow=self.pointed, steps=[s.point.label if s.point else '…' for s in known],
                    step=step, progress=progress, typing=self.shown < len(seg.text),
                    paused=self.paused, finished=self.finished, speed=opts.speed, controls=True)

    def tick(self, now, opts, to_logical, key_idle=None):
        events = []; dt = max(now-self.last, 0); self.last = now
        if self.stopped or self.finished: return events
        segs = segments(self.raw, self.done)
        if self.done and not segs:
            self.finished = True
            events.append(('empty', self.raw.strip() or '(no answer)'))
            return events + [('finish', self._fade(self.raw, opts))]
        if self.step >= len(segs) or not segs[self.step].complete: return events
        seg = segs[self.step]
        if self.pointed_step != self.step:
            self.pointed_step = self.step; self.target = None
            if seg.point:
                self.target = to_logical(seg.point); self.pointed = True
                events.append(('point', (self.target, seg.point, seg.text)))
        if self.paused:
            if self.typed_at is not None: self.typed_at += dt
            return events
        self.shown = min(self.shown + 90 * opts.speed * dt, len(seg.text))
        if self.shown < len(seg.text): return events
        if self.typed_at is None: self.typed_at = now
        gated = seg.point and seg.point.action and opts.tutorial and opts.wait_for_clicks and opts.clicks_available
        if gated and self.step not in self.acted:
            since = None if self.clicked_at is None else now-self.clicked_at
            typing = (since is not None and since < 25 and opts.typing_available and
                      re.search(r'\b(type|enter)\b', seg.text, re.I) and
                      (key_idle is None or key_idle >= since or key_idle < 1.2))
            if since is None or since < .5 or typing:
                if not self.waiting:
                    self.waiting = True; events.append(('watch_clicks', True))
                    events.append(('waiting', (self.target, seg.point)))
                return events
            self._acted(events)
            if self.done and self.step == len(segs)-1:
                self.stopped = True
                return events + [('continue', None)]
            if self.step < len(segs)-1: self._advance()
            return events
        if self.done and self.step == len(segs)-1:
            if self._continues(segs, opts):
                if now-self.typed_at >= self.hold(seg, opts):
                    self.stopped = True; events.append(('continue', None))
            else:
                self.finished = True; events.append(('finish', self._fade(seg.text, opts)))
        elif now-self.typed_at >= self.hold(seg, opts): self._advance()
        return events

    def _advance(self):
        self.step += 1; self.shown = 0.; self.typed_at = None

    @staticmethod
    def _fade(text, opts):
        return min(opts.show_seconds + .04 * len(text), max(opts.show_seconds, opts.max_show_seconds))

    def control(self, name, fraction, now, opts):
        known = self.known(); events = []
        if not known or self.stopped: return events
        step = min(self.step, len(known)-1)
        if name == 'toggle': name = 'play' if self.paused or self.finished else 'pause'
        if name == 'pause':
            self.paused = True; events.append(('cancel_fade', None))
        elif name == 'play' and self.paused:
            self.paused = False
            if self.finished: events.append(('fade', opts.show_seconds))
        elif name == 'play' and self.finished: events += self._goto(0, now, True)
        elif name == 'prev': events += self._goto(max(step-1, 0), now)
        elif name == 'next' and self.waiting and step == len(known)-1 and self.done:
            self._acted(events); self.stopped = True; events.append(('continue', None))
        elif name == 'next' and step+1 < len(known): events += self._goto(step+1, now)
        elif name == 'seek':
            events += self._goto(min(int(max(0., min(1., fraction))*len(known)), len(known)-1), now)
        self.last = now
        return events

    def _goto(self, step, now, retype=False):
        events = [('cancel_fade', None)]
        if self.waiting:
            if step > self.step: self._acted(events)
            else:
                self.waiting = False; self.clicked_at = None; events.append(('watch_clicks', False))
        self.step = step; self.shown = 0. if retype else float(len(self.known()[step].text))
        self.typed_at = None if retype else now; self.finished = False
        return events
