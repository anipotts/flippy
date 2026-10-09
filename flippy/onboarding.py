"""The first-run tour: Flippy teaches itself, one thing at a time, and waits for you to do each one.

  ask (with a question filled in for you) -> pause and resume while it talks -> a follow-up (it remembers),
  skip ahead and change the speed -> a walkthrough that waits for your clicks -> circle something and ask ->
  video review (optional) -> ends in Settings, on the look.

It reacts to what you do, through the same UI events Flippy logs anyway (daemon.event): a card on the
help-mode Nudge (both platforms) says what to try next, and moves on when the matching event comes in.
Every card can skip its step or end the tour. Shown once after setup (onboarding.done), and any time with
`flippy-ask tour` or the menu's "Take the tour".
"""
import sys

from . import loop, settings

SUGGEST = {
    "ask": "Give me a quick tour of what's on my screen, one thing at a time.",
    "followup": "Go deeper: walk me through the most useful of those, step by step.",
    "follow": "How do I open System Settings?" if sys.platform == "darwin" else "How do I open Settings?",
    "draw": "What's this, and what can I do with it?",
}
PREFILL_MS = 150    # after the box opens, before filling in the suggestion


def key_label(ui, name):
    """How to press a Flippy shortcut here, for the cards: "⇧⌘Space", "double-tap ⌘", or a fallback."""
    label = ui.key_label(name) if hasattr(ui, "key_label") else None
    return label or {"ask": "your ask shortcut", "draw": "your circle shortcut", "video": "your video shortcut",
                     "pause": "your pause shortcut"}[name]


class Tour:
    """flippy: the controller (flippy/daemon.py Flippy)."""

    STEPS = ("welcome", "ask", "pause", "followup", "skip", "follow", "draw", "video", "settings")

    def __init__(self, flippy):
        self.flippy = flippy
        self.ui = flippy.ui
        self.step = None        # one of STEPS while the tour runs, else None
        self.sub = None         # where we are inside the step
        self.prefill = None     # the suggestion to fill in when the box opens next

    @property
    def running(self):
        return self.step is not None

    # --- starting and stopping
    def maybe_start(self):
        """After setup: start once, if they haven't seen (or dismissed) the tour. Retries while setup is open."""
        if settings.get("onboarding", "done") or self.running:
            return False
        pending = getattr(self.ui, "setup_pending", lambda: False)()
        if pending:
            return True  # keep checking (a loop.timeout_add source)
        self.start()
        return False

    def start(self):
        self.flippy.dismiss()
        self._go("welcome")
        return "ok"

    def stop(self, done=True):
        self.step = self.sub = self.prefill = None
        self.ui.nudge.hide()
        if done:
            settings.set("onboarding", "done", True)
        _event("tour_stop")
        return "ok"

    def command(self, cmd):
        verb = cmd.partition(" ")[2].strip()
        if verb in ("", "start"):
            return self.start()
        if verb == "stop":
            return self.stop()
        if verb == "next":
            return self.next() or "ok"
        return "usage: tour [start|stop|next]"

    def next(self):
        if self.running:
            i = self.STEPS.index(self.step)
            if i + 1 < len(self.STEPS):
                self._go(self.STEPS[i + 1])
            else:
                self.stop()

    # --- the steps
    def _go(self, step):
        self.step, self.sub, self.prefill = step, None, None
        _event("tour_step", step=step)
        k = lambda name: key_label(self.ui, name)  # noqa: E731
        if step == "welcome":
            self._card("Hi, I'm Flippy", "Want a one-minute tour? I'll show you each thing, you try it, and "
                       "I'll wait for you.", [("Not now", self._later), ("Let's go", self.next)])
        elif step == "ask":
            self.prefill = SUGGEST["ask"]
            self._card(f"Press {k('ask')}", "That's how you call me, from any app. Try it now.")
        elif step == "pause":
            self.sub = "wait_point"
            self._card("Here I go", "I answer one step at a time, pointing as I talk.")
        elif step == "followup":
            self.prefill = SUGGEST["followup"]
            self._card(f"Ask a follow-up: {k('ask')}", "I remember what we just talked about, so you can keep "
                       "going.")
        elif step == "skip":
            self.sub = "wait_point"
            self._card("Watch the panel", "It has buttons to step through my answer.")
        elif step == "follow":
            self.prefill = SUGGEST["follow"]
            self.sub = "ask"
            self._card(f"Follow along: {k('ask')}", "Ask me how to do something, and I'll walk you through it, "
                       "waiting for each of your clicks.")
        elif step == "draw":
            self.sub = "start"
            self._card(f"Circle something: {k('draw')}", "Draw around anything on screen, let go, and ask about it.")
        elif step == "video":
            self.sub = "offer"
            self._card(f"Check a video edit: {k('video')}",
                       "In your video editor, press it, play your edit back, press it again and ask. Try it now if "
                       "an editor is open, or later.", [("End tour", self.stop), ("Next", self.next)])
        elif step == "settings":
            self.flippy.open_settings()
            self._card("Make me yours", "Themes, pointers, speed and shortcuts are all in Settings. Replay this "
                       "tour from the menu any time.", [("Done", self.stop)])

    def _later(self):
        self.stop()
        _log("tour: not now (replay from the menu or `flippy-ask tour`)")

    # --- reacting to what they do (daemon.event calls this for every UI event)
    def on_event(self, name, data):
        if not self.running:
            return
        step, sub = self.step, self.sub
        if name == "box" and self.prefill:
            text, self.prefill = self.prefill, None
            loop.timeout_add(PREFILL_MS, lambda: self._fill(text) and False)
            self._card("Press Return", "I filled in a question to start with. Or type your own.")
            return
        if step == "ask" and name == "ask":
            return self.next()
        if step == "followup" and name == "ask":
            return self.next()

        if step == "pause":
            pause = key_label(self.ui, "pause")
            if sub == "wait_point" and name == "point":
                self.sub = "pause"
                self._card(f"Pause me: {pause}", "Do it while I'm talking. The pause button on my panel works too.")
            elif sub == "pause" and name == "control" and data.get("control") == "pause":
                self.sub = "resume"
                self._card("Paused", f"{pause[0].upper() + pause[1:]} again, or press play, to keep going.")
            elif sub == "resume" and name == "control" and data.get("control") == "play":
                self.sub = "rest"
                self._card("Nice", "Let me finish, then we'll keep going.")
            elif name == "answer_done":
                self.next()
            return

        if step == "skip":
            hits = self.flippy.overlay.hits
            if sub == "wait_point" and name == "point":
                if "next" in hits:
                    self.sub = "next"
                    self._card("Skip ahead", "Click ⏭ on my panel to jump to the next step. ⏮ goes back.")
                else:
                    self._speed_or_move_on(hits)
            elif sub == "next" and name == "control" and data.get("control") in ("next", "prev", "seek"):
                self._speed_or_move_on(hits)
            elif sub == "speed" and name == "control" and data.get("control") in ("speed", "speed_cycle"):
                self.sub = "rest"
                self._card("Your pace", "That speed sticks. Change it any time from the panel or Settings.")
            elif name == "answer_done":
                self.next()
            return

        if step == "follow":
            if sub == "ask" and name == "ask":
                self.sub = "wait"
            elif sub == "wait" and name == "waiting":
                self.sub = "clicking"
                self._card("Your turn", "Click where I'm pointing. I'll wait, then show you the next step.")
            elif sub == "clicking" and name == "user_click":
                self.sub = "clicked"
                self._card("That's it", "I'll keep going until it's done. Skip any step from my panel.")
            elif sub in ("wait", "clicked") and name == "answer_done":
                self.next()
            return

        if step == "draw":
            if sub == "start" and name == "draw_start":
                self.sub = "drawing"
                self._card("Draw around it", "Hold and drag around something, then let go.")
            elif sub == "drawing" and name == "drawn":
                self.sub = "ask"
                self.prefill = SUGGEST["draw"]
            elif sub == "drawing" and name == "draw_cancel":
                self.sub = "start"
                self._card(f"Circle something: {key_label(self.ui, 'draw')}", "No worries, try again.")
            elif sub == "ask" and name == "ask":
                self.sub = "answer"
            elif sub == "answer" and name == "answer_done":
                self.next()
            return

        if step == "video":
            if name == "video_start":
                self.sub = "recording"  # the recording has its own cards; we wait
            elif sub == "recording" and name == "video_cancel":
                self.sub = "offer"
                self._go("video")
            elif sub == "recording" and name == "video_ask":
                self.sub = "answer"
            elif sub == "answer" and name == "answer_done":
                self.next()

    def _speed_or_move_on(self, hits):
        if "speed_cycle" in hits or "speed" in hits:
            self.sub = "speed"
            self._card("Speed me up", "Click the speed button on my panel. Slower works too.")
        else:
            self.sub = "rest"
            self._card("Nice", "Let me finish, then we'll keep going.")

    # --- helpers
    def _fill(self, text):
        if self.flippy.box.visible:
            self.flippy.box.set_text(text)

    def _card(self, head, detail, buttons=None):
        self.ui.nudge.card(head, detail, buttons or [("End tour", self.stop), ("Skip", self.next)])


def _event(name, **data):
    from .daemon import event
    event(name, **data)


def _log(*a):
    from .daemon import log
    log(*a)
