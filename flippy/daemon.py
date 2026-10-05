"""Flippy daemon: socket listener + input box + answer card + pointer overlay + Claude session.

GTK runs on the main thread; the Agent SDK client lives on an asyncio loop in a
worker thread. Results come back to GTK through GLib.idle_add.

COSMIC quirk: unmapping a layer surface (hide or destroy) makes the compositor
drop our whole Wayland connection, and resizing a mapped one renders garbled.
So both surfaces are mapped once and never unmapped or resized:
  - the overlay is a permanent full-screen, click-through surface; the answer
    card and pointer are drawn inside it and toggled at the widget level;
  - the input box is a regular window instead (see InputBox).

Run via bin/flippy-daemon (sets LD_PRELOAD for gtk4-layer-shell).
"""
import asyncio
import json
import math
import os
import sys
import threading
import time

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from .brain import Brain, BrainError, prepare_image  # noqa: E402
from .settings_window import SettingsWindow  # noqa: E402
from . import settings, themes  # noqa: E402
from .point import image_to_logical, segments  # noqa: E402
from .screenshot import Screenshotter  # noqa: E402

SOCK_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "flippy.sock")
HIDE_SETTLE_MS = 700        # box closed -> COSMIC's dock drops its icon and re-centers (~0.5s); wait it out
ASK_TIMEOUT_S = 90
IDLE_RESET_S = 15 * 60      # fresh Claude session after this much idle (keeps context/usage small)
CARD_MARGIN_TOP = 70
CARD_MARGIN_BOTTOM = 110    # clear the dock
STEP_TYPE_CPS = 90          # walkthrough step text types in at this many chars/s, then holds:
STEP_HOLD = {"slow": (3.5, 0.07), "normal": (2.2, 0.045), "fast": (1.2, 0.025)}  # (min s, s per char)
READ_S_PER_CHAR = 0.04      # extra time the final answer stays up per character
DRAW_TIMEOUT_S = 60         # leave draw mode (and give the mouse back) if nothing happens
# Other knobs (model, effort, theme, pointer, timing) live in flippy/settings.py.

BASE_CSS = """
window.flippy-overlay, window.flippy-box { background: transparent; }
window.flippy-box entry, window.flippy-box entry:focus-within {
  outline: 0 solid transparent; outline-width: 0; outline-offset: 0; }
window.flippy-box entry > text { border: none; box-shadow: none; background: none; }
window.flippy-box .flippy-card { font-family: "Fira Sans", "Inter", "Noto Sans", sans-serif; font-size: 15px; }
"""

EMPTY_REGION = cairo.Region()
FULL_REGION = cairo.Region(cairo.RectangleInt(0, 0, 100000, 100000))


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


EVENTS_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "flippy-events.jsonl")


def event(name, **data):
    """Timestamped UI events (wall clock). Used by scripts/edit_demo.py to drive the camera."""
    try:
        with open(EVENTS_PATH, "a") as f:
            f.write(json.dumps({"t": time.time(), "ev": name, **data}) + "\n")
    except OSError:
        pass


def layer_window(app, ns, keyboard):
    win = Gtk.Window(application=app)
    win.add_css_class(ns)
    LayerShell.init_for_window(win)
    LayerShell.set_namespace(win, ns)
    LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
    LayerShell.set_keyboard_mode(win, keyboard)
    return win


class Overlay:
    """Permanent full-screen layer holding the pointer, the answer card and the user's marks.

    Everything is painted with cairo by the active theme (flippy/themes.py).
    Click-through (empty input region) except in draw mode, where the input
    region is widened to the whole surface so it catches the mouse. Only the
    mouse: it never takes keyboard focus (see InputBox for why).
    """

    def __init__(self, app):
        self.win = layer_window(app, "flippy-overlay", LayerShell.KeyboardMode.NONE)
        for e in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(self.win, e, True)
        LayerShell.set_exclusive_zone(self.win, -1)

        self.area = Gtk.DrawingArea()
        self.area.set_draw_func(self._draw)
        self.win.set_child(self.area)
        self.win.connect("map", lambda w: w.get_surface().set_input_region(EMPTY_REGION))

        self.card = None          # themes.Card being shown, or None
        self.card_mode = "top"    # "top" | "bottom" (centered) | "follow" (next to the pointer)
        self.card_t0 = 0.0
        self.meta = ""            # shown by themes that have room for it (e.g. "OPUS · LOW")
        self.target = None        # (x, y, label) in logical px: where the pointer is heading
        self.pos = None           # where the pointer is drawn right now (animated)
        self.move_from = None
        self.move_t0 = 0.0
        self.t0 = 0.0
        self.tick_id = 0

        # draw mode
        self.strokes: list[list[tuple[float, float]]] = []
        self.drawing = False
        self.on_draw_done = lambda: None
        self.on_draw_cancel = lambda: None

        # player controls (Glass/Y2K): only these rects take clicks; the rest stays click-through
        self.hits = {}            # {name: (x, y, w, h)} from the theme, refreshed every frame
        self.region_key = None    # last input region we set, to avoid resetting it every frame
        self.on_control = lambda name, frac: None
        self.pressed = (None, 0.0)
        self.slider = None        # (name, press x) while dragging the seek/speed slider
        drag = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.area.add_controller(drag)
        right = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right.connect("pressed", lambda *a: self.drawing and self.on_draw_cancel())
        self.win.add_controller(right)
        self.win.present()

    @property
    def theme(self):
        return themes.get(settings.get("look", "theme"))

    @property
    def showing(self):
        return self.card is not None or self.target is not None or bool(self.strokes)

    def show_text(self, text, error=False, at_bottom=False, header=None, follow=False, **card_fields):
        if self.card is None:
            self.card_t0 = time.monotonic()
        self.card = themes.Card(text=text, error=error, header=header, follow=bool(follow and self.target),
                                meta=self.meta, **card_fields)
        self.card_mode = "follow" if self.card.follow else ("bottom" if at_bottom else "top")
        self.win.set_opacity(1.0)
        self._ensure_tick()

    def point(self, x, y, label):
        """Move the pointer to (x, y): drop in if it's not showing yet, otherwise glide there."""
        now = time.monotonic()
        if self.pos is None:
            self.pos = (x, y)
            self.t0 = now
        else:
            self.move_from = self.pos
            self.move_t0 = now
        self.target = (x, y, label)
        self._ensure_tick()

    def clear(self, keep_marks=False):
        self.card = None
        self.target = None
        self.pos = None
        self.move_from = None
        if not keep_marks:
            self.strokes = []
        if self.tick_id and not self.strokes:
            self.area.remove_tick_callback(self.tick_id)
            self.tick_id = 0
        self.area.queue_draw()
        self.win.set_opacity(1.0)

    def _ensure_tick(self):
        if not self.tick_id:
            self.tick_id = self.area.add_tick_callback(self._tick)

    def _tick(self, *_):
        if self.target and self.move_from:
            glide = settings.get("timing", "glide_seconds") / settings.get("timing", "speed")
            k = min((time.monotonic() - self.move_t0) / glide, 1.0)
            k = k * k * (3 - 2 * k)  # smoothstep
            (fx, fy), (tx, ty) = self.move_from, self.target[:2]
            self.pos = (fx + (tx - fx) * k, fy + (ty - fy) * k)
            if k >= 1.0:
                self.move_from = None
        self.area.queue_draw()
        return True

    def pointer_style(self):
        style = settings.get("look", "pointer")
        return self.theme.pointer if style == "theme" else style

    def _card_rect(self, W, H, opts):
        cw, ch = self.theme.size(self.card, opts)
        if self.card_mode == "follow" and self.pos:
            x, y = self.pos
            right, left, below, above = themes.pointer_extent(self.pointer_style(), settings.get("look", "pointer_size"))
            flip = y + below + 4 > H
            cx = x + right + 14                     # right of the pointer...
            if cx + cw > W - 8:
                cx = x - left - 14 - cw             # ...or left of it near the edge
            cy = (y - ch - 16) if flip else (y + 16)
            cx = min(max(cx, 8), W - cw - 8)
            cy = min(max(cy, 8), H - ch - 8)
        else:
            cx = (W - cw) / 2
            cy = H - ch - CARD_MARGIN_BOTTOM if self.card_mode == "bottom" else CARD_MARGIN_TOP
        return cx, cy, cw, ch

    # --- draw mode ---
    def start_drawing(self):
        self.drawing = True
        self.strokes = []
        self.win.get_surface().set_input_region(FULL_REGION)
        self.win.set_cursor(Gdk.Cursor.new_from_name("crosshair", None))
        self.win.set_opacity(1.0)
        self._ensure_tick()

    def stop_drawing(self):
        self.drawing = False
        self.win.get_surface().set_input_region(EMPTY_REGION)
        self.win.set_cursor(None)
        self.region_key = None  # let the next frame restore the controls' region

    def _hit(self, x, y):
        for name, (rx, ry, rw, rh) in self.hits.items():
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return name, (x - rx) / rw if rw else 0
        return None, 0

    def _drag_begin(self, gesture, x, y):
        if self.drawing:
            self.strokes.append([(x, y)])
            return
        name, frac = self._hit(x, y)
        if name:
            self.pressed = (name, time.monotonic())
            if name in ("seek", "speed"):
                self.slider = (name, x)
            self.on_control(name, frac)
            self.area.queue_draw()

    def _drag_update(self, gesture, dx, dy):
        if self.drawing and self.strokes:
            x0, y0 = self.strokes[-1][0]
            self.strokes[-1].append((x0 + dx, y0 + dy))
        elif self.slider and self.slider[0] in self.hits:
            name, x0 = self.slider
            rx, _, rw, _ = self.hits[name]
            self.pressed = (name, time.monotonic())
            self.on_control(name, (x0 + dx - rx) / rw)

    def _drag_end(self, gesture, dx, dy):
        self.slider = None
        if not self.drawing or not self.strokes:
            return
        if len(self.strokes[-1]) < 4:  # a click, not a mark; keep drawing
            self.strokes.pop()
            return
        self.on_draw_done()

    def _draw_strokes(self, cr):
        r, g, b = self.theme.pen
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        for width, alpha in ((12, 0.25), (5, 1.0)):  # soft glow, then the solid line
            cr.set_line_width(width)
            cr.set_source_rgba(r, g, b, alpha)
            for stroke in self.strokes:
                if not stroke:
                    continue
                cr.move_to(*stroke[0])
                for pt in stroke[1:]:
                    cr.line_to(*pt)
                cr.stroke()

    def _draw(self, area, cr, w, h):
        if self.strokes:
            self._draw_strokes(cr)
        theme = self.theme
        now = time.monotonic()
        if self.target and self.pos:
            themes.draw_pointer(cr, theme, self.pointer_style(), *self.pos, now - self.t0,
                                settings.get("look", "pointer_size"), h)
        hits = {}
        if self.card:
            name, at = self.pressed
            opts = {"text_size": settings.get("look", "text_size"), "card_opacity": settings.get("look", "card_opacity"),
                    "controls": settings.get("look", "controls"),
                    "pressed": name if (now - at < 0.18 or self.slider) else None}
            x, y, cw, ch = self._card_rect(w, h, opts)
            theme.draw(cr, x, y, cw, ch, self.card, now - self.card_t0, opts)
            hits = theme.hit_regions(self.card, x, y, cw, ch, opts)
        self.hits = hits
        self._update_input_region()

    def _update_input_region(self):
        """Clickable = the visible card's controls only. Draw mode manages its own (full) region."""
        if self.drawing:
            return
        key = tuple(sorted((n, round(r[0]), round(r[1]), round(r[2]), round(r[3])) for n, r in self.hits.items()))
        if key == self.region_key:
            return
        self.region_key = key
        region = cairo.Region([cairo.RectangleInt(int(rx), int(ry), int(rw) + 1, int(rh) + 1)
                               for rx, ry, rw, rh in self.hits.values()]) if self.hits else EMPTY_REGION
        surface = self.win.get_surface()
        if surface is not None:
            surface.set_input_region(region)
        self.win.set_cursor(Gdk.Cursor.new_from_name("pointer", None) if self.hits else None)


class InputBox:
    """Regular (xdg_toplevel) window, created on show and destroyed on hide.

    Not a layer surface on purpose: on COSMIC a mapped layer surface can't
    give keyboard focus back (switching it to KeyboardMode.NONE keeps eating
    keys), and unmapping one kills the connection. A normal window closes
    cleanly and focus returns to the app underneath.
    """

    def __init__(self, app, on_submit, on_cancel):
        self.app = app
        self.on_submit = on_submit
        self.on_cancel = on_cancel
        self.win = None

    @property
    def visible(self):
        return self.win is not None

    def show(self):
        event("box")
        if self.win:
            self.win.present()
            return
        theme = themes.get(settings.get("look", "theme"))
        win = Gtk.Window(application=self.app, title="Flippy", decorated=False, resizable=False)
        win.set_titlebar(Gtk.Box(visible=False))  # client-side "no titlebar", so COSMIC doesn't add its own
        win.add_css_class("flippy-box")
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("flippy-card")
        card.set_size_request(560, -1)
        entry = Gtk.Entry(placeholder_text=theme.placeholder)
        hint = Gtk.Label(label="Enter to ask · Esc to close · /new fresh session · /settings", xalign=0)
        hint.add_css_class("flippy-hint")
        card.append(entry)
        card.append(hint)
        # no titlebar (see set_titlebar above), so the box itself is the drag handle:
        # grab anywhere outside the text field to move it
        handle = Gtk.WindowHandle(child=card)
        win.set_child(handle)
        entry.connect("activate", lambda e: self.on_submit(e.get_text().strip()))
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        win.add_controller(keys)
        win.connect("close-request", lambda w: (self.on_cancel(), True)[1])
        self.win = win
        self.entry = entry
        win.present()
        entry.grab_focus()

    def _on_key(self, _ctrl, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            self.on_cancel()
            return True
        return False

    def hide(self):
        if self.win:
            win, self.win = self.win, None
            GLib.idle_add(lambda: win.destroy())  # not from inside its own event handler


class Flippy:
    def __init__(self, app):
        self.app = app
        display = Gdk.Display.get_default()
        base = Gtk.CssProvider()
        base.load_from_data(BASE_CSS, -1)
        Gtk.StyleContext.add_provider_for_display(display, base, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.theme_css = Gtk.CssProvider()  # the active theme's question-box styling
        Gtk.StyleContext.add_provider_for_display(display, self.theme_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.settings_win = None
        self.overlay = Overlay(app)
        self.overlay.on_draw_done = self._draw_done
        self.overlay.on_draw_cancel = self.cancel_draw
        self.overlay.on_control = self.control
        self.box = InputBox(app, self.submit, self.dismiss)
        self.marked = False      # next question is about what the user drew
        self.gen = 0             # bumps per question; stale stream callbacks check it
        self.play = None         # playback state of the reply being shown (see _play_tick)
        self.play_id = 0
        self.draw_timeout_id = 0
        self.shooter = Screenshotter()
        self.busy = False
        self.fade_id = 0
        self.fading = False
        self.last_ask = 0.0

        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.brain = Brain()
        self._apply_claude_settings()
        self._apply_theme()
        settings.on_change(self._on_setting)
        self._run(self.brain.start(), lambda r, e: log("claude session ready" if not e else f"session start failed: {e}"))

        self.hold = app.hold()
        self._listen()
        log(f"listening on {SOCK_PATH}")

    # --- plumbing ---
    def _run(self, coro, cb, timeout=None):
        if timeout:
            coro = asyncio.wait_for(coro, timeout)
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)

        def done(f):
            err = f.exception()
            GLib.idle_add(lambda: cb(None if err else f.result(), err) and False)
        fut.add_done_callback(done)

    def _listen(self):
        try:
            os.unlink(SOCK_PATH)
        except FileNotFoundError:
            pass
        self.service = Gio.SocketService()
        self.service.add_address(Gio.UnixSocketAddress.new(SOCK_PATH), Gio.SocketType.STREAM,
                                 Gio.SocketProtocol.DEFAULT, None)
        os.chmod(SOCK_PATH, 0o600)
        self.service.connect("incoming", self._on_incoming)
        self.service.start()

    def _on_incoming(self, service, conn, _src):
        stream = Gio.DataInputStream.new(conn.get_input_stream())
        line, _ = stream.read_line_utf8(None)
        reply = self.command((line or "").strip() or "ask")
        conn.get_output_stream().write_all((reply + "\n").encode(), None)
        conn.close(None)
        return True

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
        elif cmd == "settings":
            self.open_settings()
        elif cmd == "preview":
            self.preview()
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
            GLib.idle_add(self.app.quit)
        elif cmd == "ping":
            return "pong"
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
        self.box.show()

    def submit(self, question):
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
        event("ask", question=question)
        self.busy = True
        self.gen += 1
        self._stop_playback()
        self._cancel_fade()
        self.box.hide()
        if self.marked:
            # the marks stay on screen so they're in the screenshot
            question = ("[I drew a red mark on the screen around what I'm asking about. It's my "
                        "annotation, not part of the app.]\n" + question)
        self.overlay.clear(keep_marks=self.marked)
        self.marked = False
        GLib.timeout_add(HIDE_SETTLE_MS, self._shoot, question)

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
        GLib.idle_add(lambda: self._start_playback(gen, img_size, shot_size) and False)
        raw = await self.brain.ask(question, b64, img_size,
                                   on_text=lambda d: GLib.idle_add(lambda: self._stream_text(gen, d) and False))
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
                     "pointed_step": -1, "paused": False, "finished": False}
        self.play_id = GLib.timeout_add(33, self._play_tick)

    def _stream_text(self, gen, delta):
        if self.play and self.play["gen"] == gen and not self.play["done"]:
            self.play["raw"] += delta

    def _stop_playback(self):
        if self.play_id:
            GLib.source_remove(self.play_id)
            self.play_id = 0
        self.play = None

    def _resume_ticking(self):
        if self.play and not self.play_id:
            self.play["last"] = time.monotonic()
            self.play_id = GLib.timeout_add(33, self._play_tick)

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
            if seg.point:
                x, y = image_to_logical(seg.point, pl["img"], pl["shot"], self._scale())
                self.overlay.point(x, y, seg.point.label)
                pl["pointed"] = True
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
        if pl["done"] and pl["step"] == len(segs) - 1:
            return self._finish_playback(seg.text, segs)
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
        self.overlay.show_text(seg.text[:int(pl["shown"])] or " ",
                               header=seg.point.label if seg.point else None,
                               follow=pl["pointed"],
                               at_bottom=self._card_at_bottom(segs),
                               steps=[sg.point.label if sg.point else "…" for sg in known],
                               step=step, progress=progress,
                               typing=pl["shown"] < len(seg.text),
                               paused=pl["paused"], finished=pl["finished"],
                               speed=settings.get("timing", "speed"), controls=True)

    def _card_at_bottom(self, segs):
        """Centered card (no pointer yet): keep it away from the first point."""
        pl = self.play
        for seg in segs:
            if seg.point:
                _, y = image_to_logical(seg.point, pl["img"], pl["shot"], self._scale())
                return y < self._geometry().height / 2
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
        self.overlay.area.queue_draw()

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

    # --- settings ---
    def open_settings(self):
        if self.settings_win is None:
            self.settings_win = SettingsWindow(self.app, on_preview=self.preview, on_reset=self.reset_session)
            self.settings_win.connect("close-request", lambda w: setattr(self, "settings_win", None) or False)
        self.settings_win.present()

    def set_command(self, arg):
        try:
            path, raw = arg.split(maxsplit=1)
            section, key = path.split(".")
            default = settings.DEFAULTS[section][key]
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
        self.overlay.area.queue_draw()

    def _apply_claude_settings(self):
        model, effort = settings.get("claude", "model"), settings.get("claude", "effort")
        self.brain.configure(None if model == "default" else model, effort)
        self.overlay.meta = f"{'CLAUDE' if model == 'default' else model.upper()} · {effort.upper()}"

    def _apply_theme(self):
        theme = themes.get(settings.get("look", "theme"))
        if hasattr(theme, "refresh"):
            theme.refresh()  # e.g. re-read COSMIC's colors
        self.theme_css.load_from_data(theme.box_css(), -1)

    def preview(self):
        """Fake 3-step walkthrough so theme/pointer/timing changes can be seen in place."""
        if self.busy:
            return
        self.gen += 1
        self._stop_playback()
        self._cancel_fade()
        self.overlay.clear()
        g = self._geometry()
        sc = self._scale()
        W, H = g.width, g.height
        spots = [(70, 14, "Workspaces"), (W // 2, 14, "Clock"), (W // 2, H - 40, "Dock")]
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
        self.draw_timeout_id = GLib.timeout_add_seconds(DRAW_TIMEOUT_S, self._draw_timed_out)

    def _draw_timed_out(self):
        self.draw_timeout_id = 0  # this source is finishing; don't remove it again
        self.cancel_draw()
        return False

    def _end_draw_mode(self):
        if self.draw_timeout_id:
            GLib.source_remove(self.draw_timeout_id)
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
        self.box.show()

    # --- scripted demo helpers (used by scripts/record_demo.py) ---
    def demo_type(self, text, delay_ms=55):
        if not self.box.visible:
            self.open_box()
        state = {"i": 0}

        def step():
            if not self.box.visible:
                return False
            state["i"] += 1
            self.box.entry.set_text(text[:state["i"]])
            self.box.entry.set_position(-1)
            if state["i"] >= len(text):
                GLib.timeout_add(450, lambda: self.box.visible and self.box.entry.emit("activate") and False)
                return False
            return True
        GLib.timeout_add(500, lambda: GLib.timeout_add(delay_ms, step) and False)

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
            self.overlay.area.queue_draw()
            state["i"] += 1
            if state["i"] > n:
                self._draw_done()
                if then_ask:
                    self.demo_type(then_ask)
                return False
            return True
        GLib.timeout_add(600, lambda: GLib.timeout_add(16, step) and False)

    def cancel_draw(self):
        self._end_draw_mode()
        self.marked = False
        self.overlay.clear()

    # --- fading ---
    def _schedule_fade(self, seconds):
        self._cancel_fade()
        self.fade_id = GLib.timeout_add(int(seconds * 1000), self._fade_timer)

    def _fade_timer(self):
        self.fade_id = 0  # this source is finishing; don't source_remove it in _fade_out
        self._fade_out()
        return False

    def _cancel_fade(self):
        if self.fade_id:
            GLib.source_remove(self.fade_id)
            self.fade_id = 0
        self.overlay.win.set_opacity(1.0)

    def _fade_out(self):
        if self.fade_id:  # called directly (dismiss) with a timed fade pending: drop it, or it
            GLib.source_remove(self.fade_id)  # fires later and fades out the *next* answer
        self.fade_id = 0
        if self.fading:
            return
        self.fading = True
        start = time.monotonic()

        def step():
            if self.busy or self.box.visible:  # something new started; abort the fade
                self.fading = False
                self.overlay.win.set_opacity(1.0)
                return False
            a = 1 - (time.monotonic() - start) / 0.4
            if a <= 0:
                self.fading = False
                self._stop_playback()
                self.overlay.clear()
                event("cleared")
                return False
            self.overlay.win.set_opacity(a)
            return True
        GLib.timeout_add(16, step)

    # --- monitor info (v1: single monitor) ---
    def _monitor(self):
        return Gdk.Display.get_default().get_monitors().get_item(0)

    def _geometry(self):
        return self._monitor().get_geometry()

    def _scale(self):
        mon = self._monitor()
        return mon.get_scale() if hasattr(mon, "get_scale") else float(mon.get_scale_factor())


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
    if not LayerShell.is_supported():
        sys.exit("compositor doesn't support wlr-layer-shell (or LD_PRELOAD missing)")
    app = Gtk.Application(application_id="dev.flippy.daemon", flags=Gio.ApplicationFlags.NON_UNIQUE)
    state = {}
    app.connect("activate", lambda a: state.setdefault("flippy", Flippy(a)))
    app.run(None)


if __name__ == "__main__":
    main()
