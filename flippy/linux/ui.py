"""Linux (COSMIC/Wayland) windows: gtk4-layer-shell overlay, GTK question box, portal screenshots.

COSMIC quirk: unmapping a layer surface (hide or destroy) makes the compositor
drop our whole Wayland connection, and resizing a mapped one renders garbled.
So both surfaces are mapped once and never unmapped or resized:
  - the overlay is a permanent full-screen, click-through surface; the answer
    card and pointer are drawn inside it and toggled at the widget level;
  - the input box is a regular window instead (see InputBox).

Run via bin/flippy-daemon (sets LD_PRELOAD for gtk4-layer-shell).
"""
import sys

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from .. import pointers, settings, themes  # noqa: E402
from ..overlay import OverlayBase  # noqa: E402
from . import pointer_editor  # noqa: E402
from .screenshot import Screenshotter  # noqa: E402
from .settings_window import SettingsWindow  # noqa: E402

HIDE_SETTLE_MS = 700        # box closed -> COSMIC's dock drops its icon and re-centers (~0.5s); wait it out

BASE_CSS = """
window.flippy-overlay, window.flippy-box { background: transparent; }
window.flippy-box entry, window.flippy-box entry:focus-within {
  outline: 0 solid transparent; outline-width: 0; outline-offset: 0; }
window.flippy-box entry > text { border: none; box-shadow: none; background: none; }
window.flippy-box .flippy-card { font-family: "Fira Sans", "Inter", "Noto Sans", sans-serif; font-size: 15px; }
"""

EMPTY_REGION = cairo.Region()
FULL_REGION = cairo.Region(cairo.RectangleInt(0, 0, 100000, 100000))


def layer_window(app, ns, keyboard):
    win = Gtk.Window(application=app)
    win.add_css_class(ns)
    LayerShell.init_for_window(win)
    LayerShell.set_namespace(win, ns)
    LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
    LayerShell.set_keyboard_mode(win, keyboard)
    return win


class Overlay(OverlayBase):
    """Permanent full-screen layer surface (see flippy/overlay.py for what's on it).

    Click-through (empty input region) except in draw mode, where the input
    region is widened to the whole surface so it catches the mouse. Only the
    mouse: it never takes keyboard focus (see InputBox for why).
    """

    def __init__(self, app):
        super().__init__()
        self.win = layer_window(app, "flippy-overlay", LayerShell.KeyboardMode.NONE)
        for e in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(self.win, e, True)
        LayerShell.set_exclusive_zone(self.win, -1)

        self.area = Gtk.DrawingArea()
        self.area.set_draw_func(lambda area, cr, w, h: self.paint(cr, w, h))
        self.win.set_child(self.area)
        self.win.connect("map", lambda w: w.get_surface().set_input_region(EMPTY_REGION))
        self.tick_id = 0
        self.region_key = None    # last input region we set, to avoid resetting it every frame
        self.drag_start = (0, 0)

        drag = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", lambda g, dx, dy: self.motion(self.drag_start[0] + dx, self.drag_start[1] + dy))
        drag.connect("drag-end", lambda *a: self.release())
        self.area.add_controller(drag)
        right = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right.connect("pressed", lambda *a: self.right_click())
        self.win.add_controller(right)
        self.win.present()

    def _drag_begin(self, gesture, x, y):
        self.drag_start = (x, y)
        self.press(x, y)

    def queue_draw(self):
        self.area.queue_draw()

    def set_opacity(self, a):
        self.win.set_opacity(a)

    def start_ticking(self):
        self.tick_id = self.area.add_tick_callback(lambda *a: self.tick() or True)

    def stop_ticking(self):
        if self.tick_id:
            self.area.remove_tick_callback(self.tick_id)
            self.tick_id = 0

    def set_drawing_input(self, on):
        self.win.get_surface().set_input_region(FULL_REGION if on else EMPTY_REGION)
        self.win.set_cursor(Gdk.Cursor.new_from_name("crosshair", None) if on else None)
        if not on:
            self.region_key = None  # let the next frame restore the controls' region

    def hits_changed(self):
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

    # scripted demos
    def set_text(self, text):
        self.entry.set_text(text)
        self.entry.set_position(-1)

    def activate(self):
        self.entry.emit("activate")


class Platform:
    hide_settle_ms = HIDE_SETTLE_MS

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
        self.screenshotter = Screenshotter()
        self.hold = app.hold()

    def input_box(self, on_submit, on_cancel):
        return InputBox(self.app, on_submit, on_cancel)

    def apply_theme(self, theme):
        self.theme_css.load_from_data(theme.box_css(), -1)

    def listen(self, path, handle):
        """Serve the flippy-ask socket: one command line in, handle(cmd) -> one reply line out."""
        self.service = Gio.SocketService()
        self.service.add_address(Gio.UnixSocketAddress.new(path), Gio.SocketType.STREAM,
                                 Gio.SocketProtocol.DEFAULT, None)

        def incoming(service, conn, _src):
            stream = Gio.DataInputStream.new(conn.get_input_stream())
            line, _ = stream.read_line_utf8(None)
            reply = handle((line or "").strip() or "ask")
            conn.get_output_stream().write_all((reply + "\n").encode(), None)
            conn.close(None)
            return True
        self.service.connect("incoming", incoming)
        self.service.start()

    def open_settings(self, on_preview, on_reset):
        if self.settings_win is None:
            self.settings_win = SettingsWindow(self.app, on_preview=on_preview, on_reset=on_reset)
            self.settings_win.connect("close-request", lambda w: setattr(self, "settings_win", None) or False)
        self.settings_win.present()

    def demo_pointer(self, name, on_saved):
        """Scripted demo: draw a pointer in the editor and save it."""
        ed = pointer_editor.PixelEditor(self.app, lambda n: None)
        ed.present()
        pointer_editor.demo_paint(ed, name, lambda n: on_saved(pointers.PREFIX + n))

    def quit(self):
        GLib.idle_add(self.app.quit)

    # --- monitor info (v1: single monitor) ---
    def _monitor(self):
        return Gdk.Display.get_default().get_monitors().get_item(0)

    def screen_size(self):
        g = self._monitor().get_geometry()
        return g.width, g.height

    def scale(self):
        mon = self._monitor()
        return mon.get_scale() if hasattr(mon, "get_scale") else float(mon.get_scale_factor())


def run(make_app):
    """Start GTK and call make_app(platform) once it's up."""
    if not LayerShell.is_supported():
        sys.exit("compositor doesn't support wlr-layer-shell (or LD_PRELOAD missing)")
    app = Gtk.Application(application_id="dev.flippy.daemon", flags=Gio.ApplicationFlags.NON_UNIQUE)
    state = {}
    app.connect("activate", lambda a: state.setdefault("flippy", make_app(Platform(a))))
    app.run(None)
