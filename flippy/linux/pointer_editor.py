"""Make custom pointers: a drawing canvas (pixel art or smooth), and image import with a hotspot picker.

The GTK counterpart of flippy/mac/pointer_editor.py, with the same layout and look (flippy/linux/style.py); the
drawing model is shared (flippy/pixelart.py). Both are normal windows (safe to open/close on COSMIC). On save they
call on_saved(name) so the settings window can select the new pointer.
"""
import colorsys
import math

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from . import style  # noqa: E402
from .. import pixelart, pointers  # noqa: E402
from ..pixelart import BRUSHES, CELL, GRID_H, GRID_W, PALETTE, PixelArt, checker, from_hex, to_hex  # noqa: E402

SIDE_W = 292      # the controls column


def _heading(text):
    lab = style.label(text, "heading")
    lab.set_margin_top(6)
    return lab


def _strip(items):
    """Outlined buttons that share their edges (tools, styles, brushes)."""
    box = Gtk.Box()
    for b in items:
        box.append(b)
    return box


def _area(w, h, draw, press=None, drag=None, release=None):
    """A cairo view; press(x, y, right), drag(x, y), release()."""
    area = Gtk.DrawingArea(content_width=w, content_height=h, halign=Gtk.Align.START, valign=Gtk.Align.START)
    area.set_draw_func(lambda _a, cr, aw, ah: draw(cr, aw, ah))
    if press or drag:
        gesture = Gtk.GestureDrag(button=0)
        start = [0, 0]

        def begin(g, x, y):
            start[:] = [x, y]
            if press:
                press(x, y, g.get_current_button() == Gdk.BUTTON_SECONDARY
                      or bool(g.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK))
        gesture.connect("drag-begin", begin)
        if drag:
            gesture.connect("drag-update", lambda g, dx, dy: drag(start[0] + dx, start[1] + dy))
        if release:
            gesture.connect("drag-end", lambda *a: release())
        area.add_controller(gesture)
    return area


class PixelEditor(Gtk.Window):
    def __init__(self, app, on_saved, name=None):
        super().__init__(application=app, title="Draw a pointer", resizable=False)
        style.apply(self)
        self.set_titlebar(style.headerbar("Draw a pointer"))
        self.on_saved = on_saved
        self.editing = name
        self.art = PixelArt(name)
        self.color = (0, 0, 0)
        self.hsv = colorsys.rgb_to_hsv(*self.color)
        self.mode = "hsb"
        self.tool = "pencil"
        self.mirror = False
        self.erasing = False

        root = Gtk.Box(spacing=16, margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        self.canvas = _area(GRID_W * CELL, GRID_H * CELL, lambda cr, w, h: self.art.draw_canvas(cr, w, h, self.mirror),
                            self._press, self._drag, self._release)
        frame = Gtk.Box(css_classes=["card"], valign=Gtk.Align.START)
        frame.append(self.canvas)
        root.append(frame)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        side.set_size_request(SIDE_W, -1)
        root.append(side)

        side.append(_heading("Tools"))
        row = Gtk.Box()
        self.tools = []
        for title, key, tip in (("Pencil", "pencil", "Click paints, right-click (or Ctrl-click) erases"),
                                ("Fill", "fill", "Fill an area"),
                                ("Tip", "hotspot", "Click the pixel that should touch the target")):
            b = style.button(title, lambda key=key: self._set_tool(key), "tool")
            b.set_tooltip_text(tip)
            self.tools.append((key, b))
        row.append(_strip(b for _, b in self.tools))
        row.append(Gtk.Box(hexpand=True))
        row.append(style.button("Undo", self._undo))
        side.append(row)
        self._set_tool("pencil")
        mirror = Gtk.CheckButton(label="Mirror ↔", margin_top=4)
        mirror.connect("toggled", lambda b: self._set_mirror(b.get_active()))
        side.append(mirror)

        # pixel art, or a normal drawing; the tip snaps to the grid either way
        side.append(_heading("Style"))
        row = Gtk.Box()
        self.modes = [(pixel, style.button(title, lambda pixel=pixel: self._set_pixel(pixel), "tool"))
                      for title, pixel in (("Pixels", True), ("Smooth", False))]
        row.append(_strip(b for _, b in self.modes))
        row.append(Gtk.Box(hexpand=True))
        self.brushes = []
        for width, title in zip(BRUSHES, ("Thin", "Medium", "Thick")):
            b = style.button(title, lambda width=width: self._set_brush(width), "tool")
            b.set_tooltip_text("Brush width for smooth drawing")
            self.brushes.append((width, b))
        row.append(_strip(b for _, b in self.brushes))
        side.append(row)
        self._show_style()

        side.append(_heading("Color"))
        grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        self.swatches = []
        for i, col in enumerate(PALETTE):
            sw = _area(30, 30, lambda cr, w, h, c=col: self._swatch(cr, w, h, c))
            b = Gtk.Button(child=sw, css_classes=["swatch"],
                           tooltip_text="Eraser (transparent)" if col is None else to_hex(col))
            b.connect("clicked", lambda *_, c=col: self._pick(c))
            grid.attach(b, i % 6, i // 6, 1, 1)
            self.swatches.append(sw)
        side.append(grid)
        # the chosen color, its hex code, and the eyedropper
        row = Gtk.Box(spacing=8, margin_top=4)
        self.current = _area(44, 26, lambda cr, w, h: self._swatch(cr, w, h, self.color, True))
        self.current.set_valign(Gtk.Align.CENTER)
        row.append(self.current)
        self.hex = Gtk.Entry(text=to_hex(self.color), placeholder_text="#RRGGBB", width_chars=8, max_width_chars=8)
        self.hex.set_size_request(96, -1)
        self.hex.update_property([Gtk.AccessibleProperty.LABEL], ["Hex color"])
        self.hex.connect("activate", lambda *_: self._typed_hex())
        row.append(self.hex)
        row.append(Gtk.Box(hexpand=True))
        self.dropper = style.button("Eyedropper", self._eyedropper)
        self.dropper.set_tooltip_text("Pick a color from anywhere on the screen")
        row.append(self.dropper)
        side.append(row)
        # hue, saturation, brightness, or (the RGB button) red, green, blue 0-255
        self.sliders, self.letters, self.values = [], [], []
        for i in range(3):
            row = Gtk.Box(spacing=6)
            letter = style.label("H", "muted", "small")
            letter.set_size_request(16, -1)
            row.append(letter)
            sl = _area(SIDE_W - 22 - 40, 20, lambda cr, w, h, i=i: self._draw_slider(cr, w, h, i),
                       press=lambda x, y, right, i=i: self._slide(i, x), drag=lambda x, y, i=i: self._slide(i, x))
            row.append(sl)
            value = style.label("000", "small", xalign=1.0)
            value.set_size_request(34, -1)
            row.append(value)
            side.append(row)
            self.letters.append(letter)
            self.sliders.append(sl)
            self.values.append(value)
        row = Gtk.Box()
        row.append(Gtk.Box(hexpand=True))
        self.mode_button = style.button("RGB", self._toggle_mode)
        self.mode_button.set_tooltip_text("Switch between hue/saturation/brightness and red/green/blue (0-255) sliders")
        row.append(self.mode_button)
        side.append(row)
        self._show_mode()

        side.append(_heading("Start from"))
        row = Gtk.Box(spacing=6)
        for title, fn in (("Blank", lambda: self._do(self.art.blank)),
                          ("Hand", lambda: self._do(self.art.start, "hand")),
                          ("Arrow", lambda: self._do(self.art.start, "arrow"))):
            row.append(style.button(title, fn))
        side.append(row)

        side.append(_heading("Preview"))
        self.preview = _area(SIDE_W, 110, self.art.draw_preview)
        side.append(self.preview)

        self.name = Gtk.Entry(text=name or pointers.unique_name("My pointer"), margin_top=10)
        self.name.update_property([Gtk.AccessibleProperty.LABEL], ["Pointer name"])
        side.append(self.name)
        row = Gtk.Box(margin_top=2)
        self.flip = Gtk.CheckButton(label="Flip near bottom", active=pointers.meta(name)["flip"] if name else True,
                                    hexpand=True)
        row.append(self.flip)
        save = style.button("Save", self._save)
        row.append(save)
        side.append(row)
        self.set_child(root)
        self.set_default_widget(save)

    # ---- tools
    def _set_mirror(self, on):
        self.mirror = on
        self._redraw()

    def _set_pixel(self, pixel):
        self.art.set_pixel(pixel)
        self._show_style()
        self._redraw()

    def _set_brush(self, width):
        self.art.brush = width
        self._show_style()

    def _show_style(self):
        for pixel, b in self.modes:
            style.set_selected(b, pixel == self.art.pixel)
        for width, b in self.brushes:
            b.set_sensitive(not self.art.pixel)
            style.set_selected(b, width == self.art.brush and not self.art.pixel)

    def _set_tool(self, key):
        self.tool = key
        for k, b in self.tools:
            style.set_selected(b, k == key)

    def _pick(self, color, keep_hsv=False):
        self.color = color
        if color is not None:
            if not keep_hsv:
                self.hsv = colorsys.rgb_to_hsv(*color)
            if not self.hex.has_focus():
                self.hex.set_text(to_hex(color))
        for view in self.swatches + self.sliders + [self.current]:
            view.queue_draw()
        self._show_values()

    def _typed_hex(self):
        rgb = from_hex(self.hex.get_text())
        if rgb is None:
            self.hex.set_text(to_hex(self.color) if self.color else "")
            return
        self.hex.set_text(to_hex(rgb))
        self._pick(rgb)

    def _eyedropper(self):
        """The Screenshot portal's color picker: click anywhere on screen."""
        from .screenshot import Screenshotter

        def picked(rgb, failed):
            if rgb is not None:
                self._pick(rgb)
            elif failed:  # some portals answer PickColor with an error (COSMIC's from mid-2026 did)
                self.dropper.set_label("Not available")
                self.dropper.set_tooltip_text("The desktop's color picker didn't work. Type the color's hex code "
                                              "instead.")
                GLib.timeout_add_seconds(3, lambda: self.dropper.set_label("Eyedropper") or False)
        try:
            Screenshotter().pick_color(picked)
        except Exception:  # no session bus or portal
            picked(None, True)

    def _toggle_mode(self):
        self.mode = "rgb" if self.mode == "hsb" else "hsb"
        self._show_mode()

    def _show_mode(self):
        names = ("Red", "Green", "Blue") if self.mode == "rgb" else ("Hue", "Saturation", "Brightness")
        for letter, sl, name in zip(self.letters, self.sliders, names):
            letter.set_label(name[0])
            sl.update_property([Gtk.AccessibleProperty.LABEL], [name])
            sl.queue_draw()
        self.mode_button.set_label("HSB" if self.mode == "rgb" else "RGB")
        self._show_values()

    def _rgb(self):
        return self.color if self.color is not None else colorsys.hsv_to_rgb(*self.hsv)

    def _show_values(self):
        for view, text in zip(self.values, pixelart.slider_texts(self.mode, self._rgb(), self.hsv)):
            view.set_label(text)

    def _slide(self, i, px):
        w = self.sliders[i].get_width()
        rgb, self.hsv = pixelart.slide(self.mode, i, (px - 7) / (w - 14), self._rgb(), self.hsv)
        self._pick(rgb, keep_hsv=True)

    def _draw_slider(self, cr, w, h, i):
        """A gradient track (the hue spectrum, or this color from gray / from black) with a sharp knob."""
        hue, sat, val = self.hsv
        track = cairo.LinearGradient(7, 0, w - 7, 0)
        if self.mode == "rgb":  # this color with the channel at 0 .. at 255
            rgb = self._rgb()
            for f in (0, 1):
                track.add_color_stop_rgb(f, *[f if k == i else c for k, c in enumerate(rgb)])
        else:
            for k in range(13 if i == 0 else 2):
                f = k / (12 if i == 0 else 1)
                hsv = (f, 1, 1) if i == 0 else ((hue, f, val) if i == 1 else (hue, sat, f))
                track.add_color_stop_rgb(f, *colorsys.hsv_to_rgb(*hsv))
        cr.rectangle(7.5, h / 2 - 4, w - 15, 8)
        cr.set_source(track)
        cr.fill_preserve()
        cr.set_source_rgb(*style.OUTLINE)
        cr.set_line_width(1)
        cr.stroke()
        kx = 7 + (w - 14) * pixelart.slider_at(self.mode, i, self._rgb(), self.hsv)
        cr.rectangle(round(kx) - 3.5, 1.5, 8, h - 3)
        cr.set_source_rgb(*style.TEXT)
        cr.fill_preserve()
        cr.set_source_rgb(0, 0, 0)
        cr.stroke()

    def _do(self, fn, *args):
        fn(*args)
        self._redraw()

    def _undo(self):
        self._do(self.art.undo)
        self._show_style()  # undo can switch the style back

    def _press(self, x, y, right):
        cell = self.art.cell_at(x, y)
        if not cell:
            return
        self.art.snapshot()
        self.erasing = right
        color = None if right else self.color
        if self.tool == "hotspot":
            self.art.hotspot = cell  # the tip is a grid cell in both styles
        elif self.tool == "fill":
            self.art.fill(cell, color) if self.art.pixel else self.art.fill_smooth(x, y, color)
        elif self.art.pixel:
            self.art.paint(cell, color, self.mirror)
        else:
            self.art.stroke_to(x, y, color, self.mirror)
        self._redraw()

    def _drag(self, x, y):
        if self.tool != "pencil":
            return
        color = None if self.erasing else self.color
        if not self.art.pixel:
            self.art.stroke_to(x, y, color, self.mirror)
            self._redraw()
            return
        cell = self.art.cell_at(x, y)
        if cell:
            self.art.paint(cell, color, self.mirror)
            self._redraw()

    def _release(self):
        self.art.end_stroke()

    def _redraw(self):
        self.canvas.queue_draw()
        self.preview.queue_draw()

    def _swatch(self, cr, w, h, col, current=False):
        if col is None:
            checker(cr, 0, 0, w, h, 6)
            cr.set_source_rgb(1, 0.2, 0.2)
            cr.set_line_width(2)
            cr.move_to(3, h - 3)
            cr.line_to(w - 3, 3)
            cr.stroke()
        else:
            cr.set_source_rgb(*col)
            cr.rectangle(0, 0, w, h)
            cr.fill()
        chosen = not current and col == self.color
        cr.rectangle(1, 1, w - 2, h - 2) if chosen else cr.rectangle(0.5, 0.5, w - 1, h - 1)
        cr.set_source_rgb(*(style.TEXT if chosen else style.OUTLINE))
        cr.set_line_width(2 if chosen else 1)
        cr.stroke()

    def _save(self):
        name = self.art.save(self.name.get_text(), self.editing, self.flip.get_active())
        self.on_saved(name)
        self.close()


def demo_paint(ed, name, on_done):
    """Scripted demo (`flippy-ask demo-pointer`): paint pixelart.DEMO_SPRITE in the editor like a person would,
    then name and save it."""
    def done():
        ed.name.set_text(name)
        ed._save()
        on_done(name)
    pixelart.demo_paint(ed.art, ed._redraw, ed._set_tool, lambda col: setattr(ed, "color", col), done)


class HotspotPicker(Gtk.Window):
    """After importing an image: click where it should touch the target."""

    VIEW = 360

    def __init__(self, app, on_saved, name, surf, editing=False):
        super().__init__(application=app, title="Set the pointer's tip", resizable=False)
        style.apply(self)
        self.set_titlebar(style.headerbar("Set the pointer's tip"))
        self.on_saved = on_saved
        self.surf = surf
        self.editing = name if editing else None
        m = pointers.meta(name) if editing else None
        iw, ih = surf.get_width(), surf.get_height()
        self.k = self.VIEW / max(iw, ih)
        self.hotspot = tuple(m["hotspot"]) if m else (iw // 2, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=16, margin_bottom=16,
                      margin_start=16, margin_end=16)
        box.set_size_request(388, -1)
        box.append(style.label("Click the spot that should touch what Flippy points at.", wrap=True, width=388))
        self.area = _area(int(iw * self.k), int(ih * self.k), self._draw, press=self._click)
        self.area.set_halign(Gtk.Align.CENTER)
        box.append(self.area)
        self.pixel = Gtk.CheckButton(label="Pixel art (keep it crisp)", active=m["pixel"] if m else max(iw, ih) <= 48)
        self.flip = Gtk.CheckButton(label="Flip near the bottom of the screen", active=m["flip"] if m else False)
        box.append(self.pixel)
        box.append(self.flip)
        row = Gtk.Box(spacing=8, margin_top=4)
        self.name = Gtk.Entry(text=name, hexpand=True)
        row.append(self.name)
        save = style.button("Save", self._save)
        row.append(save)
        box.append(row)
        self.set_child(box)
        self.set_default_widget(save)

    def _draw(self, cr, w, h):
        checker(cr, 0, 0, w, h, 10)
        cr.save()
        cr.scale(self.k, self.k)
        pat = cairo.SurfacePattern(self.surf)
        pat.set_filter(cairo.FILTER_NEAREST if self.k >= 2 else cairo.FILTER_GOOD)
        cr.set_source(pat)
        cr.paint()
        cr.restore()
        hx, hy = self.hotspot
        cx, cy = (hx + 0.5) * self.k, (hy + 0.5) * self.k
        cr.set_source_rgb(1, 0.2, 0.2)
        cr.set_line_width(2)
        cr.arc(cx, cy, 9, 0, 2 * math.pi)
        cr.move_to(cx - 14, cy)
        cr.line_to(cx + 14, cy)
        cr.move_to(cx, cy - 14)
        cr.line_to(cx, cy + 14)
        cr.stroke()

    def _click(self, x, y, right):
        self.hotspot = (min(int(x / self.k), self.surf.get_width() - 1), min(int(y / self.k), self.surf.get_height() - 1))
        self.area.queue_draw()

    def _save(self):
        name = self.name.get_text().strip() or "Image pointer"
        if self.editing and name != self.editing:
            pointers.delete(self.editing)
        pointers.save(name, self.surf, self.hotspot, pixel=self.pixel.get_active(), flip=self.flip.get_active())
        self.on_saved(name)
        self.close()


def import_image(parent, app, on_saved):
    """File picker -> downscale -> hotspot picker."""
    dialog = Gtk.FileDialog(title="Choose a pointer image")
    filt = Gtk.FileFilter(name="Images")
    for mime in ("image/png", "image/jpeg", "image/svg+xml", "image/gif", "image/webp", "image/bmp"):
        filt.add_mime_type(mime)
    store = Gio.ListStore.new(Gtk.FileFilter)
    store.append(filt)
    dialog.set_filters(store)

    def done(dlg, res):
        try:
            f = dlg.open_finish(res)
        except GLib.Error:
            return  # cancelled
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file(f.get_path())
        except GLib.Error as e:
            err = Gtk.AlertDialog(message="Couldn't open that image", detail=str(e))
            err.show(parent)
            return
        w, h = pix.get_width(), pix.get_height()
        k = min(pointers.MAX_IMPORT_PX / max(w, h), 1.0)
        if k < 1:
            pix = pix.scale_simple(max(1, round(w * k)), max(1, round(h * k)), GdkPixbuf.InterpType.HYPER)
        if not pix.get_has_alpha():
            pix = pix.add_alpha(False, 0, 0, 0)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, pix.get_width(), pix.get_height())
        cr = cairo.Context(surf)
        Gdk.cairo_set_source_pixbuf(cr, pix, 0, 0)
        cr.paint()
        surf.flush()
        base = f.get_basename().rsplit(".", 1)[0]
        picker = HotspotPicker(app, on_saved, pointers.unique_name(base), surf)
        picker.set_transient_for(parent)
        picker.present()

    dialog.open(parent, None, done)


def edit(app, on_saved, name):
    """Reopen a custom pointer in the matching editor."""
    m = pointers.meta(name)
    surf = pointers.surface(name)
    if surf is None:
        return
    if (m["pixel"] and surf.get_width() <= GRID_W and surf.get_height() <= GRID_H) or m["grid_h"]:
        PixelEditor(app, on_saved, name).present()  # pixel art, or a smooth drawing made in it
    else:
        HotspotPicker(app, on_saved, name, surf, editing=True).present()
