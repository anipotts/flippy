"""Flippy daemon: socket listener + input box + answer card + pointer overlay + Claude session.

This is the shared controller. The windows, screenshots and socket come from the
platform layer: flippy/linux/ui.py (GTK + layer-shell) or flippy/mac/ui.py (AppKit).
The UI runs on the main thread; the Agent SDK client lives on an asyncio loop in a
worker thread. Results come back to the main thread through loop.idle_add.
"""
import asyncio
import json
import math
import os
import re
import sys
import tempfile
import threading
import time

from . import loop, settings, themes, tips, watch
from .brain import Brain, BrainError, prepare_image
from .point import image_to_logical, segments

RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()  # macOS: the per-user $TMPDIR
SOCK_PATH = os.path.join(RUNTIME_DIR, "flippy.sock")
ASK_TIMEOUT_S = 90
IDLE_RESET_S = 15 * 60      # fresh Claude session after this much idle (keeps context/usage small)
STEP_TYPE_CPS = 90          # walkthrough step text types in at this many chars/s, then holds:
STEP_HOLD = {"slow": (3.5, 0.07), "normal": (2.2, 0.045), "fast": (1.2, 0.025)}  # (min s, s per char)
READ_S_PER_CHAR = 0.04      # extra time the final answer stays up per character
DRAW_TIMEOUT_S = 60         # leave draw mode (and give the mouse back) if nothing happens
TIPS_RETRY_S = 300          # after a failed tip deck write, wait this long before trying again
CLICK_RADIUS = 55           # a click this close (logical px) to a :click step's target counts as doing it
CLICK_SETTLE_S = 0.5        # after their click, let the app react before moving on
# Other knobs (model, effort, theme, pointer, timing) live in flippy/settings.py.


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


EVENTS_PATH = os.path.join(RUNTIME_DIR, "flippy-events.jsonl")


def event(name, **data):
    """Timestamped UI events (wall clock). Used by scripts/edit_demo.py to drive the camera."""
    try:
        with open(EVENTS_PATH, "a") as f:
            f.write(json.dumps({"t": time.time(), "ev": name, **data}) + "\n")
    except OSError:
        pass


class Flippy:
    def __init__(self, ui):
        self.ui = ui
        self.overlay = ui.overlay
        self.overlay.on_draw_done = self._draw_done
        self.overlay.on_draw_cancel = self.cancel_draw
        self.overlay.on_control = self.control
        self.box = ui.input_box(self.submit, self.dismiss)
        self.marked = False      # next question is about what the user drew
        self.gen = 0             # bumps per question; stale stream callbacks check it
        self.play = None         # playback state of the reply being shown (see _play_tick)
        self.play_id = 0
        self.draw_timeout_id = 0
        self.shooter = ui.screenshotter
        self.busy = False
        self.tutorial = False    # the current answer is a tutorial: its ":click" steps wait for their click
        self.fade_id = 0
        self.fading = False
        self.last_ask = 0.0

        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.brain = Brain()
        self._apply_claude_settings()
        self._apply_theme()
        settings.on_change(self._on_setting)
        self.watcher = watch.Watcher()
        self.dealer = tips.Dealer()
        self.decks = {}          # app id -> tips.Deck
        self.writing = set()     # apps whose tips are being written
        self.tips_failed = {}    # app id -> when writing its tips last failed
        self.watch_id = 0
        self.sampling = False
        self._apply_help_settings()
        self._run(self.brain.start(), lambda r, e: log("claude session ready" if not e else f"session start failed: {e}"))

        try:
            os.unlink(SOCK_PATH)
        except FileNotFoundError:
            pass
        ui.listen(SOCK_PATH, self.command)
        os.chmod(SOCK_PATH, 0o600)
        log(f"listening on {SOCK_PATH}")

    # --- plumbing ---
    def _run(self, coro, cb, timeout=None):
        if timeout:
            coro = asyncio.wait_for(coro, timeout)
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)

        def done(f):
            err = f.exception()
            loop.idle_add(lambda: cb(None if err else f.result(), err) and False)
        fut.add_done_callback(done)

    def command(self, cmd):
        log("cmd:", cmd)
        if cmd == "ask":
            self.open_box()
        elif cmd == "draw":
            self.start_draw()
        elif cmd.startswith("demo-type "):  # scripted demo: type into the box like a person
            self.demo_type(cmd[len("demo-type "):])
        elif cmd.startswith("demo-draw "):  # scripted demo: circle (cx, cy, rx, ry) in logical px, then ask
            parts = cmd.split(maxsplit=5)
            self.demo_draw(*map(float, parts[1:5]), then_ask=parts[5] if len(parts) > 5 else None)
        elif cmd.startswith("demo-pointer"):  # scripted demo: draw a pointer in the editor, save, preview it
            self.demo_pointer(cmd[len("demo-pointer"):].strip() or "Sunset")
        elif cmd == "settings":
            self.open_settings()
        elif cmd == "setup" and hasattr(self.ui, "open_setup"):  # macOS first-run window
            self.ui.open_setup()
        elif cmd == "preview":
            self.preview()
        elif cmd.startswith("demo-point "):  # demo-point <x> <y> <label>|<text>: one pointed step, logical px
            x, y, rest = cmd.split(maxsplit=3)[1:]
            label, _, text = rest.partition("|")
            self.demo_point(float(x), float(y), label, text or label)
        elif cmd == "demo-tutorial":  # a fake tutorial whose first step waits for you to click the Apple menu
            self.preview(tutorial=True)
        elif cmd.startswith("demo-user-click "):  # demo-user-click <x> <y>: as if they clicked there (tests)
            x, y = map(float, cmd.split()[1:3])
            self._on_user_click(x, y)
        elif cmd.startswith("control "):  # same as clicking a player button: control <name> [0-1 for seek/speed]
            parts = cmd.split()
            self.control(parts[1], float(parts[2]) if len(parts) > 2 else 0.0)
        elif cmd.startswith("set "):  # set <section.key> <value>, e.g. `flippy-ask set look.theme y2k`
            return self.set_command(cmd[4:])
        elif cmd == "dismiss":
            self.dismiss()
        elif cmd == "reset":
            self.reset_session()
        elif cmd == "quit":
            self.ui.quit()
        elif cmd == "ping":
            return "pong"
        elif cmd.startswith("help-mode "):  # help-mode off|quiet
            return self.set_command("help.mode " + cmd.split(maxsplit=1)[1])
        elif cmd.startswith("demo-nudge"):  # the "need a hand?" card: demo-nudge [stalled|circles|dialog] [app name]
            parts = cmd.split(maxsplit=2)
            reason = parts[1] if len(parts) > 1 else "stalled"
            offer = watch.Offer("demo", parts[2] if len(parts) > 2 else "Ableton Live", reason)
            self.ui.show_nudge(offer, lambda: self._nudge_help(offer), lambda: log("nudge: not now"),
                               lambda: log("nudge: mute"))
        elif cmd.startswith("shot "):  # shot <path.png>: screenshot through Flippy's permission (demo scripts)
            self.ui.screenshot_to(cmd[5:].strip())
        elif cmd.startswith("record "):  # record start <path.mov> | record stop
            parts = cmd.split(maxsplit=2)
            if parts[1] == "start" and len(parts) == 3:
                self.ui.start_recording(parts[2])
                event("record_start", path=parts[2])
            else:
                self.ui.stop_recording()
                event("record_stop")
        elif cmd.startswith("click "):  # click <x> <y> [double]: logical px, top-left origin (Settings: automation)
            return self.click_command(cmd[6:].split())
        elif cmd.startswith("nudge "):  # nudge <button title>: press a button on the help card (demo scripts)
            return "ok" if self.ui.press_nudge(cmd[6:].strip()) else "no such button"
        elif cmd.startswith("goal "):  # goal <app id> <what they want to do>: steers that app's tips
            parts = cmd.split(maxsplit=2)
            if len(parts) < 3:
                return "usage: goal <app id> <what you want to do>"
            self.set_goal(parts[1], parts[2])
        elif cmd.startswith("demo-tip"):  # demo-tip [app id]: that app's next real tip, else a sample one
            parts = cmd.split(maxsplit=1)
            deck = tips.Deck.load(parts[1]) if len(parts) > 1 else None
            tip = deck.next_tip() if deck else None
            if tip:
                self._show_tip(deck, tip)
            else:
                self._show_tip(tips.Deck("demo", "Ableton Live"), {"text": "Hold ⌘ while dragging a clip to duplicate "
                                                                           "it instead of moving it.", "level": 1,
                                                                   "state": "new"})
        elif cmd.startswith("watch-app "):  # watch-app <app id>: toggle help mode for that app
            self.toggle_watch_app(cmd.split(maxsplit=1)[1])
        elif cmd.startswith("q "):  # ask without the box (scripting/testing)
            self.submit(cmd[2:].strip())
        else:
            return f"unknown command: {cmd}"
        return "ok"

    # --- flow ---
    def open_box(self):
        if self.busy:
            return
        if self.overlay.drawing:
            self.cancel_draw()
        if self.box.visible:  # hotkey again toggles the box closed
            self.box.hide()
            return
        self._cancel_fade()  # keep the last answer up while typing a follow-up
        self._show_box()

    def _show_box(self):
        event("box")
        self.box.show()

    def submit(self, question, tutorial=None):
        """tutorial: steps they have to do wait for their click (":click"). None = decide from the question."""
        if not question or self.busy:
            return
        if question in ("/new", "/reset"):
            self.box.hide()
            self.reset_session()
            return
        if question == "/settings":
            self.box.hide()
            self.open_settings()
            return
        self.tutorial = wants_tutorial(question) if tutorial is None else tutorial
        event("ask", question=question, tutorial=self.tutorial)
        self.busy = True
        self.gen += 1
        self._stop_playback()
        self._cancel_fade()
        self.box.hide()
        if self.marked:
            # the marks stay on screen so they're in the screenshot
            question = ("[I drew a red mark on the screen around what I'm asking about. It's my "
                        "annotation, not part of the app.]\n" + question)
        question += ("\n\n(tutorial: mark the steps I have to do myself with :click)" if self.tutorial else
                     "\n\n(not a tutorial: just answer and point, no :click)")
        self.overlay.clear(keep_marks=self.marked)
        self.marked = False
        loop.timeout_add(self.ui.hide_settle_ms, self._shoot, question)

    def _shoot(self, question):
        self.shooter.take(lambda path, err: self._on_shot(question, path, err))
        return False

    def _on_shot(self, question, path, err):
        if err:
            self._fail(f"couldn't take a screenshot: {err}")
            return
        self.overlay.show_text("thinking…", phase="thinking")
        event("thinking")
        if self.brain.dirty:
            log("model/effort changed, starting a fresh session")
            coro = self._fresh_then_ask(question, path, self.gen)
        elif self.last_ask and time.monotonic() - self.last_ask > IDLE_RESET_S:
            log("idle too long, starting a fresh session")
            coro = self._fresh_then_ask(question, path, self.gen)
        else:
            coro = self._ask(question, path, self.gen)
        self.last_ask = time.monotonic()
        self._run(coro, self._on_answer, timeout=ASK_TIMEOUT_S)

    async def _fresh_then_ask(self, question, path, gen):
        await self.brain.reset()
        return await self._ask(question, path, gen)

    async def _ask(self, question, path, gen):
        try:
            b64, img_size, shot_size = await asyncio.to_thread(prepare_image, path, settings.get("claude", "image"))
        finally:
            try:
                os.unlink(path)  # portal drops screenshots in /tmp; don't leave them around
            except OSError:
                pass
        loop.idle_add(lambda: self._start_playback(gen, img_size, shot_size) and False)
        raw = await self.brain.ask(question, b64, img_size,
                                   on_text=lambda d: loop.idle_add(lambda: self._stream_text(gen, d) and False))
        return raw, gen

    def _on_answer(self, result, err):
        self.busy = False
        if err:
            self._stop_playback()
            self._fail(_friendly_error(err))
            if not isinstance(err, BrainError):
                self._run(self.brain.reset(), lambda r, e: None)  # transport may be wedged
            return
        raw, gen = result
        log(f"answer ({self.brain.last_model}, effort {self.brain.options.effort}): {raw!r}")
        if self.play and self.play["gen"] == gen:
            self.play["raw"] = raw  # authoritative full text (deltas should already match)
            self.play["done"] = True

    # --- playback: show the reply step by step, moving the hand to each point ---
    # The player skins' controls (control()) can pause, step back/forward, seek and replay.
    def _start_playback(self, gen, img_size, shot_size):
        if gen != self.gen:
            return
        self._stop_playback()
        self.play = {"gen": gen, "raw": "", "done": False, "img": img_size, "shot": shot_size,
                     "step": 0, "shown": 0.0, "typed_at": None, "last": time.monotonic(), "pointed": False,
                     "pointed_step": -1, "paused": False, "finished": False,
                     "target": None, "waiting": False, "clicked_at": None, "acted": set()}
        self.play_id = loop.timeout_add(33, self._play_tick)

    def _stream_text(self, gen, delta):
        if self.play and self.play["gen"] == gen and not self.play["done"]:
            self.play["raw"] += delta

    def _stop_playback(self):
        if self.play and self.play["waiting"]:
            self._listen_for_click(False)
        if self.play_id:
            loop.source_remove(self.play_id)
            self.play_id = 0
        self.play = None

    def _resume_ticking(self):
        if self.play and not self.play_id:
            self.play["last"] = time.monotonic()
            self.play_id = loop.timeout_add(33, self._play_tick)

    @staticmethod
    def _hold_s(seg):
        hold_min, hold_per_char = STEP_HOLD.get(settings.get("timing", "step_pace"), STEP_HOLD["normal"])
        return (hold_min + hold_per_char * len(seg.text)) / settings.get("timing", "speed")

    def _play_tick(self):
        pl = self.play
        if pl is None:
            self.play_id = 0
            return False
        now = time.monotonic()
        dt, pl["last"] = now - pl["last"], now
        segs = segments(pl["raw"], pl["done"])
        if pl["done"] and not segs:
            segs_text = pl["raw"].strip() or "(no answer)"
            self.overlay.show_text(segs_text, progress=1.0, finished=True, controls=True)
            return self._finish_playback(segs_text, segs)
        if pl["step"] >= len(segs):
            return True  # waiting for the next step to stream in
        seg = segs[pl["step"]]
        if not seg.complete:
            return True  # wait until we know where this step points
        if pl["pointed_step"] != pl["step"]:
            pl["pointed_step"] = pl["step"]
            pl["target"] = None
            if seg.point:
                x, y = image_to_logical(seg.point, pl["img"], pl["shot"], self._scale())
                self.overlay.point(x, y, seg.point.label)
                pl["pointed"] = True
                pl["target"] = (x, y)
                event("point", x=x, y=y, label=seg.point.label, text=seg.text)
        if pl["paused"]:
            if pl["typed_at"]:
                pl["typed_at"] += dt  # freeze the hold timer
            self._render_step(pl, segs, now)
            return True
        # type the step's text in, then hold it long enough to read
        pl["shown"] = min(pl["shown"] + STEP_TYPE_CPS * settings.get("timing", "speed") * dt, len(seg.text))
        self._render_step(pl, segs, now)
        if pl["shown"] < len(seg.text):
            return True
        if pl["typed_at"] is None:
            pl["typed_at"] = now
        if self._gated(seg) and pl["step"] not in pl["acted"]:
            # a step they have to do: hold here until they click the thing (flippy/point.py ":click")
            if pl["clicked_at"] is None or now - pl["clicked_at"] < CLICK_SETTLE_S:
                if not pl["waiting"]:
                    pl["waiting"] = True
                    self._listen_for_click(True)
                    event("waiting", x=pl["target"][0], y=pl["target"][1], label=seg.point.label)
                    self._render_step(pl, segs, now)
                return True
            self._step_done(pl)
            if pl["done"] and pl["step"] == len(segs) - 1:
                self._continue_tutorial()
                return False
            if pl["step"] < len(segs) - 1:
                pl["step"] += 1
                pl["shown"] = 0.0
                pl["typed_at"] = None
            return True
        if pl["done"] and pl["step"] == len(segs) - 1:
            if self._tutorial_goes_on(pl, segs) and now - pl["typed_at"] >= self._hold_s(seg):
                self._continue_tutorial()  # they did the last step; Claude just added a remark after it
                return False
            if not self._tutorial_goes_on(pl, segs):
                return self._finish_playback(seg.text, segs)
            return True
        if now - pl["typed_at"] >= self._hold_s(seg):
            pl["step"] += 1
            pl["shown"] = 0.0
            pl["typed_at"] = None
        return True

    def _render_step(self, pl, segs, now):
        known = [sg for sg in segs if sg.complete]
        if not known:
            return
        step = min(pl["step"], len(known) - 1)
        seg = known[step]
        if pl["finished"]:
            progress = 1.0 if step == len(known) - 1 else (step + 1) / len(known)
        else:
            frac = (pl["shown"] / max(len(seg.text), 1)) * 0.5
            if pl["typed_at"]:
                frac += min((now - pl["typed_at"]) / self._hold_s(seg), 1) * 0.5
            progress = (step + frac) / len(known)
        text = seg.text[:int(pl["shown"])] or " "
        if pl["waiting"] and step == pl["step"]:
            text += "\n→ Your turn: click it"
        self.overlay.show_text(text,
                               header=seg.point.label if seg.point else None,
                               follow=pl["pointed"],
                               at_bottom=self._card_at_bottom(segs),
                               steps=[sg.point.label if sg.point else "…" for sg in known],
                               step=step, progress=progress,
                               typing=pl["shown"] < len(seg.text),
                               paused=pl["paused"], finished=pl["finished"],
                               speed=settings.get("timing", "speed"), controls=True)

    # --- tutorials: steps marked :click wait for them to click the thing ---
    def _gated(self, seg):
        return bool(seg.point and seg.point.action and self.tutorial and settings.get("timing", "wait_for_clicks")
                    and hasattr(self.ui, "watch_clicks"))

    def _listen_for_click(self, on):
        if hasattr(self.ui, "watch_clicks"):
            self.ui.watch_clicks(self._on_user_click) if on else self.ui.unwatch_clicks()

    def _on_user_click(self, x, y):
        pl = self.play
        if pl and pl["waiting"] and pl["target"] and pl["clicked_at"] is None:
            tx, ty = pl["target"]
            if math.hypot(x - tx, y - ty) <= CLICK_RADIUS * settings.get("look", "pointer_size") ** 0.5:
                pl["clicked_at"] = time.monotonic()
                event("user_click", x=x, y=y)

    def _tutorial_goes_on(self, pl, segs):
        """In a tutorial, after they did the reply's last step-to-do, only remarks without a point followed:
        the screen has probably changed, so look again instead of ending."""
        if not (self.tutorial and pl["acted"]):
            return False
        last_pointed = max((i for i, sg in enumerate(segs) if sg.point), default=-1)
        return max(pl["acted"]) >= last_pointed

    def _step_done(self, pl):
        pl["acted"].add(pl["step"])
        pl["waiting"] = False
        pl["clicked_at"] = None
        self._listen_for_click(False)

    def _continue_tutorial(self):
        """They did the last step we could see: take a fresh screenshot and ask for what's next."""
        log("tutorial: they did it, asking for the next step")
        event("tutorial_continue")
        self._stop_playback()
        self.submit("Done, I did that. Continue the walkthrough from here.", tutorial=True)

    def _card_at_bottom(self, segs):
        """Centered card (no pointer yet): keep it away from the first point."""
        pl = self.play
        for seg in segs:
            if seg.point:
                _, y = image_to_logical(seg.point, pl["img"], pl["shot"], self._scale())
                return y < self.ui.screen_size()[1] / 2
        return False

    def _finish_playback(self, last_text, segs):
        event("answer_done")
        self.play_id = 0
        pl = self.play
        pl["finished"] = True  # keep the state around so the controls can step back / replay
        if segs:
            self._render_step(pl, segs, time.monotonic())
        if not pl["paused"]:
            show_s = settings.get("timing", "show_seconds")
            self._schedule_fade(min(show_s + READ_S_PER_CHAR * len(last_text),
                                    max(show_s, settings.get("timing", "max_show_seconds"))))
        return False

    # --- player controls (clicked on the Glass/Y2K skins) ---
    def control(self, name, frac=0.0):
        log("control:", name, f"{frac:.2f}" if name in ("seek", "speed") else "")
        event("control", control=name)
        self.overlay.pressed = (name, time.monotonic())  # light the button up, also when scripted
        if name in ("stop", "close", "min"):
            self.dismiss()
            return
        if name == "speed":
            settings.set("timing", "speed", themes.frac_to_speed(frac))
            return
        if name == "speed_cycle":
            options = [0.5, 0.75, 1.0, 1.5, 2.0]
            cur = settings.get("timing", "speed")
            settings.set("timing", "speed", next((o for o in options if o > cur + 0.01), options[0]))
            return
        pl = self.play
        if not pl:
            return
        known = [sg for sg in segments(pl["raw"], pl["done"]) if sg.complete]
        if not known:
            return
        step = min(pl["step"], len(known) - 1)
        if name == "toggle":  # Glass orb: play/pause in one button
            name = "play" if (pl["paused"] or pl["finished"]) else "pause"
        if name == "pause":
            self._set_paused(True)
        elif name == "play":
            if pl["paused"]:
                self._set_paused(False)
            elif pl["finished"]:
                self._goto(0, retype=True)  # replay from the top
        elif name == "prev":
            self._goto(max(step - 1, 0))
        elif name == "next" and pl["waiting"] and step == len(known) - 1 and pl["done"]:
            self._step_done(pl)  # skipping the last step they could do: on to the next screenful
            self._continue_tutorial()
        elif name == "next" and step + 1 < len(known):
            self._goto(step + 1)
        elif name == "seek":
            self._goto(min(int(frac * len(known)), len(known) - 1))

    def _set_paused(self, paused):
        pl = self.play
        pl["paused"] = paused
        if paused:
            self._cancel_fade()  # stay up while paused
        elif pl["finished"]:
            self._schedule_fade(settings.get("timing", "show_seconds"))
        self._resume_ticking()
        self._refresh_card()

    def _goto(self, k, retype=False):
        pl = self.play
        if pl["waiting"]:
            if k > pl["step"]:
                self._step_done(pl)  # skipping ahead counts as done
            else:
                pl["waiting"], pl["clicked_at"] = False, None
                self._listen_for_click(False)
        known = [sg for sg in segments(pl["raw"], pl["done"]) if sg.complete]
        pl["step"] = k
        pl["shown"] = 0.0 if retype else float(len(known[k].text))  # stepping shows the text in full
        pl["typed_at"] = None if retype else time.monotonic()
        pl["finished"] = False
        self._cancel_fade()
        self._resume_ticking()

    def _refresh_card(self):
        if self.play:
            self._render_step(self.play, segments(self.play["raw"], self.play["done"]), time.monotonic())
        elif self.overlay.card:
            self.overlay.card.speed = settings.get("timing", "speed")
        self.overlay.queue_draw()

    def _fail(self, msg):
        self.busy = False
        self._stop_playback()
        log("error:", msg)
        self.overlay.clear()
        self.overlay.show_text(msg, error=True)
        self._schedule_fade(settings.get("timing", "show_seconds"))

    def reset_session(self):
        self.overlay.show_text("starting a fresh session…")

        def done(_r, e):
            if e:
                self._fail(f"reset failed: {e}")
            else:
                self.overlay.show_text("fresh session ready")
                self._schedule_fade(2)
        self._run(self.brain.reset(), done)

    def dismiss(self):
        self.box.hide()
        self._stop_playback()
        self.marked = False
        if self.overlay.drawing:
            self.cancel_draw()
        elif self.overlay.showing:
            self._fade_out()

    # --- help mode: offer a hand when they seem stuck (flippy/watch.py) ---
    def _apply_help_settings(self):
        self.watcher.apps = settings.get_list("help", "apps")
        self.watcher.muted = settings.get_list("help", "muted")
        on = settings.get("help", "mode") != "off" and hasattr(self.ui, "sample")
        if on and not self.watch_id:
            self.watch_id = loop.timeout_add(int(watch.SAMPLE_S * 1000), self._watch_tick)
            log(f"help mode on, watching {sorted(self.watcher.apps) or 'no apps yet'}")
        elif not on and self.watch_id:
            loop.source_remove(self.watch_id)
            self.watch_id = 0
            self.watcher.reset()
            self.ui.hide_nudge()
            log("help mode off")

    def toggle_watch_app(self, app):
        apps = settings.get_list("help", "apps")
        apps.symmetric_difference_update({app})
        settings.set_list("help", "apps", apps)
        if app in apps and settings.get("help", "mode") == "off":
            settings.set("help", "mode", "quiet")  # picking an app to watch turns help mode on

    def _watch_tick(self):
        if (self.busy or self.box.visible or self.overlay.showing or self.overlay.drawing
                or self.ui.nudge_visible() or self.sampling):
            self.watcher.reset()  # Flippy's own stuff on screen isn't the person being stuck
            self.dealer.reset()
            return True
        if not self.watcher.apps:
            return True
        self.sampling = True

        def work():  # the screen thumbnail takes ~100 ms: off the main thread
            try:
                s = self.ui.sample()
            except Exception as e:
                log(f"help mode: sampling failed: {e}")
                s = None
            loop.idle_add(lambda: self._watch_feed(s) and False)
        threading.Thread(target=work, daemon=True).start()
        return True

    def _watch_feed(self, sample):
        self.sampling = False
        if sample is None or self.busy or self.box.visible or self.overlay.showing:
            return
        offer = self.watcher.feed(sample)
        tip_time = settings.get("help", "mode") == "tips" and self.dealer.feed(sample, self.watcher.apps,
                                                                               self.watcher.muted)
        if offer:
            log(f"help mode: offering a hand in {offer.app_name} ({offer.reason})")
            event("nudge", app=offer.app, reason=offer.reason)
            self.dealer.shown(sample.t)  # no tip right on the heels of an offer
            self.ui.show_nudge(offer, lambda: self._nudge_help(offer), lambda: self.watcher.not_now(offer.app),
                               lambda: self._nudge_mute(offer))
            return
        if settings.get("help", "mode") == "tips" and sample.app in self.watcher.apps:
            deck = self._deck(sample.app, sample.app_name)
            tip = deck.next_tip() if tip_time else None
            if tip:
                self.dealer.shown(sample.t)
                self._show_tip(deck, tip)

    # --- tips mode (flippy/tips.py): a cached deck per app, dealt out locally ---
    def _deck(self, app, name):
        deck = self.decks.get(app) or tips.Deck.load(app) or tips.Deck(app, name or app)
        if name and deck.app_name != name:
            deck.app_name = name
        self.decks[app] = deck
        if deck.needs_refill():
            self._write_tips(deck)
        return deck

    def _write_tips(self, deck):
        if deck.app in self.writing or time.monotonic() - self.tips_failed.get(deck.app, -1e9) < TIPS_RETRY_S:
            return
        self.writing.add(deck.app)
        n = tips.REFILL_SIZE if deck.tips else tips.DECK_SIZE
        log(f"tips: writing {n} tips for {deck.app_name}" + (f" (goal: {deck.goal})" if deck.goal else ""))

        def done(new, err):
            self.writing.discard(deck.app)
            if err:
                log(f"tips: couldn't write tips for {deck.app_name}: {err}")
                self.tips_failed[deck.app] = time.monotonic()
                return
            before = len(deck.tips)
            deck.add(new)
            deck.save()
            log(f"tips: {len(deck.tips) - before} new tips for {deck.app_name}")
        self._run(self.brain.write_tips(deck.app_name, deck.goal, n, deck.texts()), done, timeout=180)

    def _show_tip(self, deck, tip):
        log(f"tips: showing a level-{tip['level']} tip in {deck.app_name}")
        event("tip", app=deck.app, text=tip["text"])

        def mark(state):
            deck.mark(tip, state)
            if deck.app != "demo":
                deck.save()

        def show_me():
            mark("shown")
            self.submit(f"I'm learning {deck.app_name} and got this tip: \"{tip['text']}\" "
                        f"Show me where that is on my screen right now, step by step.", tutorial=True)
        self.ui.show_tip(deck.app_name, tip["text"], got_it=lambda: mark("shown"), knew=lambda: mark("knew"),
                         show_me=show_me)

    def set_goal(self, app, goal, name=None):
        """A new goal for an app: drop its unseen tips and write fresh ones for the goal."""
        deck = self.decks.get(app) or tips.Deck.load(app) or tips.Deck(app, name or app)
        if name:
            deck.app_name = name
        self.tips_failed.pop(app, None)
        deck.goal = goal.strip()
        deck.tips = [t for t in deck.tips if t["state"] != "new"]
        deck.save()
        self.decks[app] = deck
        self._write_tips(deck)

    def _nudge_help(self, offer):
        self.watcher.helped(offer.app)
        self.submit(offer.question(), tutorial=True)

    def _nudge_mute(self, offer):
        self.watcher.mute(offer.app)
        settings.set_list("help", "muted", settings.get_list("help", "muted") | {offer.app})

    # --- settings ---
    def open_settings(self):
        self.ui.open_settings(on_preview=self.preview, on_reset=self.reset_session)

    def click_command(self, args):
        """Scripted clicks for demos and automation. Off unless turned on in Settings; Claude never triggers these."""
        if not settings.get("automation", "clicks"):
            return "clicks are off: turn on Settings > Hotkeys > Let scripts click (automation.clicks)"
        if not hasattr(self.ui, "click"):
            return "clicks aren't supported on this platform yet"
        try:
            x, y = float(args[0]), float(args[1])
        except (IndexError, ValueError):
            return "usage: click <x> <y> [double]"
        log(f"click at {x:.0f},{y:.0f}" + (" (double)" if "double" in args[2:] else ""))
        return self.ui.click(x, y, double="double" in args[2:])

    def set_command(self, arg):
        try:
            path, raw = arg.split(maxsplit=1)
            section, key = path.split(".")
            default = settings.DEFAULTS[section][key]
            if isinstance(default, bool):
                value = raw.lower() in ("1", "true", "on", "yes")
            else:
                value = type(default)(float(raw)) if isinstance(default, (int, float)) else raw
            if not settings._valid(section, key, value):
                return f"invalid value for {path}; choices: {settings.CHOICES.get((section, key), type(default).__name__)}"
            settings.set(section, key, value)
            return "ok"
        except (ValueError, KeyError):
            return "usage: set <section.key> <value>  (see ~/.config/flippy/config.toml)"

    def _on_setting(self, section, key, value):
        log(f"setting {section}.{key} = {value!r}")
        if section == "claude" and key in ("model", "effort"):
            self._apply_claude_settings()
        elif section == "look" and key == "theme":
            self._apply_theme()
        elif section == "timing" and key == "speed":
            self._refresh_card()
        elif section == "help":
            self._apply_help_settings()
        self.overlay.queue_draw()

    def _apply_claude_settings(self):
        model, effort = settings.get("claude", "model"), settings.get("claude", "effort")
        self.brain.configure(None if model == "default" else model, effort)
        self.overlay.meta = f"{'CLAUDE' if model == 'default' else model.upper()} · {effort.upper()}"

    def _apply_theme(self):
        theme = themes.get(settings.get("look", "theme"))
        if hasattr(theme, "refresh"):
            theme.refresh()  # e.g. re-read COSMIC's colors
        self.ui.apply_theme(theme)

    def demo_point(self, x, y, label, text):
        """A one-step answer pointing at (x, y): same spot every time, so a theme/pointer montage lines up."""
        if self.busy:
            return
        self.gen += 1
        self._stop_playback()
        self._cancel_fade()
        self.overlay.clear()
        self.tutorial = False
        W, H = self.ui.screen_size()
        sc = self._scale()
        shot = (int(W * sc), int(H * sc))
        self._start_playback(self.gen, shot, shot)
        self.play["raw"], self.play["done"] = f"{text} [POINT:{int(x * sc)},{int(y * sc)}:{label}]", True

    def preview(self, tutorial=False):
        """Fake 3-step walkthrough so theme/pointer/timing changes can be seen in place.
        tutorial: the first step is a ":click" step that waits for them to click it."""
        if self.busy:
            return
        self.gen += 1
        self._stop_playback()
        self._cancel_fade()
        self.overlay.clear()
        W, H = self.ui.screen_size()
        sc = self._scale()
        spots = [(70, 14, "Workspaces"), (W // 2, 14, "Clock"), (W // 2, H - 40, "Dock")]
        self.tutorial = tutorial
        if tutorial:
            spots = [(22, 12, "Apple menu:click"), (W // 2, H - 40, "Dock")]
            texts = ("Click the Apple menu to open it", "Nice. That's how tutorials wait for you, then go on")
            raw = " ".join(f"{txt} [POINT:{int(x * sc)},{int(y * sc)}:{lbl}]." for (x, y, lbl), txt in zip(spots, texts))
            shot = (int(W * sc), int(H * sc))
            self._start_playback(self.gen, shot, shot)
            self.play["raw"], self.play["done"] = raw, True
            return
        raw = " ".join(f"{txt} [POINT:{int(x * sc)},{int(y * sc)}:{lbl}]." for (x, y, lbl), txt in zip(spots, (
            "This is a preview of how answers look: the pointer starts at the workspaces button",
            "then glides to the clock while the panel follows it",
            "and ends on the dock, one step per thing it explains")))
        shot = (int(W * sc), int(H * sc))
        self._start_playback(self.gen, shot, shot)
        self.play["raw"], self.play["done"] = raw, True

    # --- draw mode: circle something, then ask about it ---
    def start_draw(self):
        if self.busy:
            return
        if self.overlay.drawing:  # hotkey again = cancel
            self.cancel_draw()
            return
        self.box.hide()
        self._cancel_fade()
        self.overlay.clear()
        self.overlay.start_drawing()
        event("draw_start")
        self.overlay.show_text("draw around something, then let go to ask · right-click to cancel")
        self.draw_timeout_id = loop.timeout_add_seconds(DRAW_TIMEOUT_S, self._draw_timed_out)

    def _draw_timed_out(self):
        self.draw_timeout_id = 0  # this source is finishing; don't remove it again
        self.cancel_draw()
        return False

    def _end_draw_mode(self):
        if self.draw_timeout_id:
            loop.source_remove(self.draw_timeout_id)
            self.draw_timeout_id = 0
        self.overlay.stop_drawing()

    def _draw_done(self):
        pts = [p for st in self.overlay.strokes for p in st]
        if pts:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            event("drawn", x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys))
        self._end_draw_mode()
        self.overlay.clear(keep_marks=True)  # drop the hint, keep the marks
        self.marked = True
        self._show_box()

    # --- scripted demo helpers (used by scripts/record_demo.py) ---
    def demo_type(self, text, delay_ms=55):
        if not self.box.visible:
            self.open_box()
        state = {"i": 0}

        def step():
            if not self.box.visible:
                return False
            state["i"] += 1
            self.box.set_text(text[:state["i"]])
            if state["i"] >= len(text):
                loop.timeout_add(450, lambda: self.box.visible and self.box.activate() and False)
                return False
            return True
        loop.timeout_add(500, lambda: loop.timeout_add(delay_ms, step) and False)

    def demo_draw(self, cx, cy, rx, ry, then_ask=None, duration_ms=900):
        self.start_draw()
        self.overlay.strokes = [[]]
        n = duration_ms // 16
        state = {"i": 0}

        def step():
            if not self.overlay.drawing or not self.overlay.strokes:
                return False
            a = 2 * math.pi * 1.08 * state["i"] / n - math.pi / 2  # a bit past full circle, like a hand would
            self.overlay.strokes[-1].append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
            self.overlay.queue_draw()
            state["i"] += 1
            if state["i"] > n:
                self._draw_done()
                if then_ask:
                    self.demo_type(then_ask)
                return False
            return True
        loop.timeout_add(600, lambda: loop.timeout_add(16, step) and False)

    def demo_pointer(self, name):
        def saved(value):
            settings.set("look", "pointer", value)
            loop.timeout_add(500, lambda: self.preview() and False)
        self.ui.demo_pointer(name, saved)

    def cancel_draw(self):
        self._end_draw_mode()
        self.marked = False
        self.overlay.clear()

    # --- fading ---
    def _schedule_fade(self, seconds):
        self._cancel_fade()
        self.fade_id = loop.timeout_add(int(seconds * 1000), self._fade_timer)

    def _fade_timer(self):
        self.fade_id = 0  # this source is finishing; don't source_remove it in _fade_out
        self._fade_out()
        return False

    def _cancel_fade(self):
        if self.fade_id:
            loop.source_remove(self.fade_id)
            self.fade_id = 0
        self.overlay.set_opacity(1.0)

    def _fade_out(self):
        if self.fade_id:  # called directly (dismiss) with a timed fade pending: drop it, or it
            loop.source_remove(self.fade_id)  # fires later and fades out the *next* answer
        self.fade_id = 0
        if self.fading:
            return
        self.fading = True
        start = time.monotonic()

        def step():
            if self.busy or self.box.visible:  # something new started; abort the fade
                self.fading = False
                self.overlay.set_opacity(1.0)
                return False
            a = 1 - (time.monotonic() - start) / 0.4
            if a <= 0:
                self.fading = False
                self._stop_playback()
                self.overlay.clear()
                event("cleared")
                return False
            self.overlay.set_opacity(a)
            return True
        loop.timeout_add(16, step)

    def _scale(self):
        return self.ui.scale()


TUTORIAL_RE = re.compile(r"\b(how (do|can|would|should|to) (i|you|we)|how to|walk me|teach me|show me how|guide me|"
                         r"step[- ]by[- ]step|steps (to|for)|where do i (click|find|go)|help me (set up|make|create|add|"
                         r"build|record|install|do))\b")


def wants_tutorial(question):
    """Is this a "how do I do X" question (a tutorial, steps wait for their clicks) or just a question?"""
    return bool(TUTORIAL_RE.search(question.lower()))


def _friendly_error(err):
    s = str(err) or type(err).__name__
    low = s.lower()
    if isinstance(err, (asyncio.TimeoutError, TimeoutError)):
        return "Claude took too long to answer. Try again."
    if "rate_limit" in low or "usage limit" in low or "limit reached" in low or "429" in low:
        return f"Usage limit hit on your Claude plan. ({s})"
    if "authentication" in low or "login" in low or "401" in low:
        return "Not logged in to Claude Code. Run `claude` in a terminal and /login."
    if "network" in low or "connect" in low or "dns" in low or "offline" in low:
        return f"Can't reach Claude (network?). ({s})"
    return f"Something went wrong: {s}"


def main():
    themes.load_fonts()  # bundled pixel font for the Y2K theme, process-local
    if sys.platform == "darwin":
        from .mac import ui
    else:
        from .linux import ui
    ui.run(Flippy)


if __name__ == "__main__":
    main()
