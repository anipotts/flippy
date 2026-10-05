"""Spike 0: full-screen, transparent, click-through layer-shell overlay.

Draws a dot + label at a hard-coded logical (x, y), plus corner markers so we
can see the overlay covers the whole monitor. Quits after DURATION seconds.

Run:  python3 spikes/spike0_overlay.py [x y]  (with the gtk4-layer-shell env from bin/flippy-daemon)
"""
import sys

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

X, Y = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) == 3 else (400, 300)
DURATION = 20


def draw(area, cr, w, h):
    # corner markers (20px squares) to prove we span the full output
    cr.set_source_rgba(1, 0, 1, 0.8)
    for cx, cy in ((0, 0), (w - 20, 0), (0, h - 20), (w - 20, h - 20)):
        cr.rectangle(cx, cy, 20, 20)
        cr.fill()
    # pointer dot with ring
    cr.set_source_rgba(0.2, 0.6, 1.0, 0.35)
    cr.arc(X, Y, 22, 0, 6.2832)
    cr.fill()
    cr.set_source_rgba(0.2, 0.6, 1.0, 1.0)
    cr.arc(X, Y, 8, 0, 6.2832)
    cr.fill()
    # label pill
    label = f"spike0 ({X},{Y})  surface {w}x{h}"
    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(15)
    ext = cr.text_extents(label)
    lx, ly = X + 28, Y - 12
    cr.set_source_rgba(0.1, 0.1, 0.12, 0.9)
    cr.rectangle(lx - 8, ly - 4, ext.width + 16, ext.height + 12)
    cr.fill()
    cr.set_source_rgba(1, 1, 1, 1)
    cr.move_to(lx, ly + ext.height + 1)
    cr.show_text(label)


def make_click_through(win):
    surface = win.get_surface()
    if surface is not None:
        surface.set_input_region(cairo.Region())  # empty region = all clicks pass through


def on_activate(app):
    win = Gtk.Window(application=app)
    LayerShell.init_for_window(win)
    LayerShell.set_namespace(win, "flippy-overlay")
    LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
    for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
        LayerShell.set_anchor(win, edge, True)
    LayerShell.set_exclusive_zone(win, -1)  # ignore panels, cover everything
    LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.NONE)

    css = Gtk.CssProvider()
    css.load_from_data(b"window { background: transparent; }", -1)
    Gtk.StyleContext.add_provider_for_display(win.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    area = Gtk.DrawingArea()
    area.set_draw_func(draw)
    win.set_child(area)

    win.connect("realize", lambda w: make_click_through(w))
    win.connect("map", lambda w: make_click_through(w))
    win.present()

    mon = win.get_display().get_monitors().get_item(0)
    g = mon.get_geometry()
    print(f"layer-shell supported: {LayerShell.is_supported()}")
    print(f"monitor0: {mon.get_connector()} logical {g.width}x{g.height}+{g.x}+{g.y} scale {mon.get_scale_factor()} "
          f"fractional {getattr(mon, 'get_scale', lambda: 'n/a')()}")
    print(f"dot at logical ({X},{Y}); quitting in {DURATION}s", flush=True)
    GLib.timeout_add_seconds(DURATION, app.quit)


app = Gtk.Application(application_id="dev.flippy.spike0")
app.connect("activate", on_activate)
app.run(None)
