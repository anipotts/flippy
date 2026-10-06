"""Make custom pointers: a pixel-art canvas, and image import with a hotspot picker.

Both are normal windows (safe to open/close on COSMIC). On save they call
on_saved(name) so the settings window can select the new pointer.
"""
import math

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from .. import pointers, themes  # noqa: E402

GRID_W, GRID_H = 20, 24
CELL = 18
PALETTE = [None, (0, 0, 0), (1, 1, 1), (0.55, 0.55, 0.6), (1.0, 0.25, 0.2), (1.0, 0.6, 0.1), (1.0, 0.9, 0.2),
           (0.2, 0.85, 0.35), (0.25, 0.6, 1.0), (0.6, 0.35, 0.95), (1.0, 0.5, 0.75), (0.55, 0.35, 0.2)]


def _checker(cr, x, y, w, h, sq=6):
    cr.set_source_rgb(0.32, 0.32, 0.35)
    cr.rectangle(x, y, w, h)
    cr.fill()
    cr.set_source_rgb(0.42, 0.42, 0.45)
    for j in range(int(h // sq) + 1):
        for i in range(int(w // sq) + 1):
            if (i + j) % 2:
                cr.rectangle(x + i * sq, y + j * sq, min(sq, w - i * sq), min(sq, h - j * sq))
    cr.fill()


def _from_sprite(grid_rows, tip_col):
    """Built-in sprite (# outline . fill) -> centered grid + hotspot."""
    cells = [[None] * GRID_W for _ in range(GRID_H)]
    ox = (GRID_W - len(grid_rows[0])) // 2
    oy = (GRID_H - len(grid_rows)) // 2
    for r, row in enumerate(grid_rows):
        for c, ch in enumerate(row):
            if ch != " ":
                cells[oy + r][ox + c] = (0, 0, 0) if ch == "#" else (1, 1, 1)
    return cells, (ox + tip_col, oy)


class PixelEditor(Gtk.Window):
    def __init__(self, app, on_saved, name=None):
        super().__init__(application=app, title="Draw a pointer", default_width=760, default_height=560)
        self.on_saved = on_saved
        self.editing = name
        self.cells = [[None] * GRID_W for _ in range(GRID_H)]
        self.hotspot = (GRID_W // 2, 0)
        self.color = (0, 0, 0)
        self.tool = "pencil"
        self.undo = []
        if name:
            self._load(name)

        root = Gtk.Box(spacing=16, margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        self.canvas = Gtk.DrawingArea(content_width=GRID_W * CELL, content_height=GRID_H * CELL)
        self.canvas.set_draw_func(self._draw_canvas)
        drag = Gtk.GestureDrag(button=0)
        drag.connect("drag-begin", self._press)
        drag.connect("drag-update", self._drag)
        self.canvas.add_controller(drag)
        frame = Gtk.Frame(child=self.canvas, valign=Gtk.Align.START)
        root.append(frame)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, hexpand=True)
        side.append(self._label("Tools"))
        tools = Gtk.Box(spacing=4)
        group = None
        self.tool_buttons = {}
        for key, label in (("pencil", "✏ Pencil"), ("fill", "🪣 Fill"), ("hotspot", "◎ Tip")):
            b = Gtk.ToggleButton(label=label)
            if group:
                b.set_group(group)
            group = group or b
            b.set_active(key == "pencil")
            b.connect("toggled", lambda b, k=key: b.get_active() and setattr(self, "tool", k))
            self.tool_buttons[key] = b
            b.set_tooltip_text({"pencil": "Left-click paints, right-click erases",
                                "fill": "Fill an area with the color",
                                "hotspot": "Click the pixel that should touch the target"}[key])
            tools.append(b)
        side.append(tools)
        opts = Gtk.Box(spacing=12)
        self.mirror = Gtk.CheckButton(label="Mirror ↔")
        opts.append(self.mirror)
        undo = Gtk.Button(label="↶ Undo")
        undo.connect("clicked", lambda *_: self._undo())
        opts.append(undo)
        side.append(opts)

        side.append(self._label("Color"))
        pal = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6, min_children_per_line=6,
                          column_spacing=4, row_spacing=4)
        for col in PALETTE:
            sw = Gtk.DrawingArea(content_width=26, content_height=26)
            sw.set_draw_func(self._draw_swatch, col)
            btn = Gtk.Button(child=sw)
            btn.add_css_class("flat")
            btn.set_tooltip_text("Eraser (transparent)" if col is None else None)
            btn.connect("clicked", lambda *_, c=col: setattr(self, "color", c))
            pal.append(btn)
        side.append(pal)
        custom = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
        custom.connect("notify::rgba", lambda b, _p: setattr(self, "color", (b.get_rgba().red, b.get_rgba().green,
                                                                            b.get_rgba().blue)))
        row = Gtk.Box(spacing=6)
        row.append(Gtk.Label(label="Custom:"))
        row.append(custom)
        side.append(row)

        side.append(self._label("Start from"))
        starts = Gtk.Box(spacing=4)
        for label, fn in (("Blank", self._blank), ("Hand", lambda: self._start(themes.HAND, themes.HAND_TIP_COL)),
                          ("Arrow", lambda: self._start(themes.ARROW, 0))):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda *_, f=fn: f())
            starts.append(b)
        side.append(starts)

        side.append(self._label("Preview"))
        self.preview = Gtk.DrawingArea(content_width=260, content_height=110)
        self.preview.set_draw_func(self._draw_preview)
        side.append(self.preview)

        bottom = Gtk.Box(spacing=8, valign=Gtk.Align.END, vexpand=True)
        self.name = Gtk.Entry(text=name or pointers.unique_name("My pointer"), hexpand=True)
        bottom.append(self.name)
        self.flip = Gtk.CheckButton(label="Flip near bottom", active=pointers.meta(name)["flip"] if name else True)
        bottom.append(self.flip)
        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda *_: self._save())
        bottom.append(save)
        side.append(bottom)
        root.append(side)
        self.set_child(root)

    @staticmethod
    def _label(text):
        lab = Gtk.Label(label=text, xalign=0)
        lab.add_css_class("heading")
        return lab

    # ---- model
    def _snapshot(self):
        self.undo.append(([row[:] for row in self.cells], self.hotspot))
        self.undo = self.undo[-50:]

    def _undo(self):
        if self.undo:
            self.cells, self.hotspot = self.undo.pop()
            self._redraw()

    def _blank(self):
        self._snapshot()
        self.cells = [[None] * GRID_W for _ in range(GRID_H)]
        self._redraw()

    def _start(self, rows, tip):
        self._snapshot()
        self.cells, self.hotspot = _from_sprite(rows, tip)
        self._redraw()

    def _load(self, name):
        surf = pointers.surface(name)
        if surf is None:
            return
        w, h = min(surf.get_width(), GRID_W), min(surf.get_height(), GRID_H)
        data, stride = surf.get_data(), surf.get_stride()
        for yy in range(h):
            for xx in range(w):
                b, g, r, a = data[yy * stride + xx * 4: yy * stride + xx * 4 + 4]
                if a > 127:  # premultiplied ARGB32, little-endian -> BGRA bytes
                    self.cells[yy][xx] = (r / a, g / a, b / a)
        self.hotspot = tuple(pointers.meta(name)["hotspot"])

    def _cell_at(self, x, y):
        cx, cy = int(x // CELL), int(y // CELL)
        return (cx, cy) if 0 <= cx < GRID_W and 0 <= cy < GRID_H else None

    def _paint(self, cell, color):
        cx, cy = cell
        self.cells[cy][cx] = color
        if self.mirror.get_active():
            self.cells[cy][GRID_W - 1 - cx] = color

    def _fill(self, cell, color):
        cx, cy = cell
        target = self.cells[cy][cx]
        if target == color:
            return
        stack = [cell]
        while stack:
            x, y = stack.pop()
            if 0 <= x < GRID_W and 0 <= y < GRID_H and self.cells[y][x] == target:
                self.cells[y][x] = color
                stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]

    def _press(self, gesture, x, y):
        cell = self._cell_at(x, y)
        if not cell:
            return
        self._snapshot()
        self.erasing = gesture.get_current_button() == Gdk.BUTTON_SECONDARY
        color = None if self.erasing else self.color
        if self.tool == "hotspot":
            self.hotspot = cell
        elif self.tool == "fill":
            self._fill(cell, color)
        else:
            self._paint(cell, color)
        self.press_xy = (x, y)
        self._redraw()

    def _drag(self, gesture, dx, dy):
        if self.tool != "pencil":
            return
        x0, y0 = self.press_xy
        cell = self._cell_at(x0 + dx, y0 + dy)
        if cell:
            self._paint(cell, None if self.erasing else self.color)
            self._redraw()

    def _redraw(self):
        self.canvas.queue_draw()
        self.preview.queue_draw()

    # ---- drawing
    def _draw_canvas(self, area, cr, w, h):
        _checker(cr, 0, 0, w, h, CELL / 2)
        for y in range(GRID_H):
            for x in range(GRID_W):
                c = self.cells[y][x]
                if c is not None:
                    cr.set_source_rgb(*c)
                    cr.rectangle(x * CELL, y * CELL, CELL, CELL)
                    cr.fill()
        cr.set_source_rgba(0, 0, 0, 0.18)
        cr.set_line_width(1)
        for x in range(GRID_W + 1):
            cr.move_to(x * CELL + 0.5, 0)
            cr.line_to(x * CELL + 0.5, h)
        for y in range(GRID_H + 1):
            cr.move_to(0, y * CELL + 0.5)
            cr.line_to(w, y * CELL + 0.5)
        cr.stroke()
        if self.mirror.get_active():
            cr.set_source_rgba(0.3, 0.7, 1.0, 0.6)
            cr.move_to(GRID_W * CELL / 2, 0)
            cr.line_to(GRID_W * CELL / 2, h)
            cr.stroke()
        hx, hy = self.hotspot  # the tip: red crosshair
        cx, cy = hx * CELL + CELL / 2, hy * CELL + CELL / 2
        cr.set_source_rgb(1, 0.2, 0.2)
        cr.set_line_width(2)
        cr.arc(cx, cy, CELL * 0.45, 0, 2 * math.pi)
        cr.stroke()

    def _draw_swatch(self, area, cr, w, h, col):
        if col is None:
            _checker(cr, 0, 0, w, h, 6)
            cr.set_source_rgb(1, 0.2, 0.2)
            cr.set_line_width(2)
            cr.move_to(3, h - 3)
            cr.line_to(w - 3, 3)
            cr.stroke()
        else:
            cr.set_source_rgb(*col)
            cr.rectangle(0, 0, w, h)
            cr.fill()

    def _surface(self):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, GRID_W, GRID_H)
        cr = cairo.Context(surf)
        for y in range(GRID_H):
            for x in range(GRID_W):
                c = self.cells[y][x]
                if c is not None:
                    cr.set_source_rgb(*c)
                    cr.rectangle(x, y, 1, 1)
                    cr.fill()
        surf.flush()
        return surf

    def _draw_preview(self, area, cr, w, h):
        for i, bg in enumerate(((0.12, 0.12, 0.14), (0.92, 0.92, 0.94))):
            cr.set_source_rgb(*bg)
            cr.rectangle(i * w / 2, 0, w / 2, h)
            cr.fill()
            surf = self._surface()
            px = themes.sprite_px(1.0)
            hx, hy = self.hotspot
            cx, cy = i * w / 2 + w / 4, 10
            cr.save()
            cr.translate(cx - hx * px, cy - hy * px)
            cr.scale(px, px)
            pat = cairo.SurfacePattern(surf)
            pat.set_filter(cairo.FILTER_NEAREST)
            cr.set_source(pat)
            cr.paint()
            cr.restore()

    def _save(self):
        name = self.name.get_text().strip() or "My pointer"
        if self.editing and name != self.editing:
            pointers.delete(self.editing)
        pointers.save(name, self._surface(), self.hotspot, pixel=True, flip=self.flip.get_active())
        self.on_saved(name)
        self.close()



# Scripted demo (`flippy-ask demo-pointer`): outline -> flood fill -> highlights -> sparkles -> tip.
DEMO_SPRITE = [
    "o          s   ",
    "oo           s ",
    "ofo       s    ",
    "ohfo           ",
    "ohffo          ",
    "ohfffo         ",
    "ohffffo        ",
    "ohfffffo       ",
    "ohffffffo      ",
    "ohfffffffo     ",
    "ohffffffffo    ",
    "ohfffffffffo   ",
    "ohfffffoooooo  ",
    "ohffoffo       ",
    "ohfo offo      ",
    "ofo  offo      ",
    "oo    offo     ",
    "o     offo     ",
    "       oo      ",
]
DEMO_COLORS = {"o": (0.2, 0.08, 0.38), "f": (1.0, 0.6, 0.1), "h": (1.0, 0.5, 0.75), "s": (1.0, 0.9, 0.2)}


def demo_paint(ed, name, on_done, cell_ms=34):
    """Paint DEMO_SPRITE into a PixelEditor like a person would, then name and save it."""
    ox, oy = 1, 1
    cells = {k: [(ox + c, oy + r) for r, row in enumerate(DEMO_SPRITE) for c, ch in enumerate(row) if ch == k]
             for k in "ohs"}
    steps = [("tool", "pencil"), ("color", "o")] + [("paint", xy) for xy in cells["o"]]
    steps += [("pause", 6), ("tool", "fill"), ("color", "f"), ("pause", 4), ("fill", (ox + 2, oy + 6)), ("pause", 8),
              ("tool", "pencil"), ("color", "h")] + [("paint", xy) for xy in cells["h"]]
    steps += [("color", "s")] + [("paint", xy) for xy in cells["s"]]
    steps += [("pause", 6), ("tool", "hotspot"), ("pause", 4), ("tip", (ox, oy)), ("pause", 10), ("name", name),
              ("pause", 16), ("save", None)]
    it = iter(steps)

    def tick():
        try:
            kind, arg = next(it)
        except StopIteration:
            return False
        if kind == "pause":  # wait `arg` ticks, then carry on
            GLib.timeout_add(cell_ms * arg, lambda: GLib.timeout_add(cell_ms, tick) and False)
            return False
        if kind == "tool":
            ed.tool_buttons[arg].set_active(True)
        elif kind == "color":
            ed.color = DEMO_COLORS[arg]
        elif kind == "paint":
            ed._snapshot()
            ed._paint(arg, ed.color)
        elif kind == "fill":
            ed._snapshot()
            ed._fill(arg, ed.color)
        elif kind == "tip":
            ed._snapshot()
            ed.hotspot = arg
        elif kind == "name":
            ed.name.set_text(name)
        elif kind == "save":
            ed._save()
            on_done(name)
            return False
        ed._redraw()
        return True
    GLib.timeout_add(700, lambda: GLib.timeout_add(cell_ms, tick) and False)


class HotspotPicker(Gtk.Window):
    """After importing an image: click where it should touch the target."""

    VIEW = 360

    def __init__(self, app, on_saved, name, surf, editing=False):
        super().__init__(application=app, title="Set the pointer's tip", default_width=420, default_height=560)
        self.on_saved = on_saved
        self.surf = surf
        self.editing = name if editing else None
        m = pointers.meta(name) if editing else None
        iw, ih = surf.get_width(), surf.get_height()
        self.k = self.VIEW / max(iw, ih)
        self.hotspot = tuple(m["hotspot"]) if m else (iw // 2, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=16, margin_bottom=16,
                      margin_start=16, margin_end=16)
        box.append(Gtk.Label(label="Click the spot that should touch what Flippy points at.", wrap=True, xalign=0))
        self.area = Gtk.DrawingArea(content_width=int(iw * self.k), content_height=int(ih * self.k),
                                    halign=Gtk.Align.CENTER)
        self.area.set_draw_func(self._draw)
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        self.area.add_controller(click)
        box.append(self.area)
        self.pixel = Gtk.CheckButton(label="Pixel art (keep it crisp)",
                                     active=m["pixel"] if m else max(iw, ih) <= 48)
        self.flip = Gtk.CheckButton(label="Flip near the bottom of the screen", active=m["flip"] if m else False)
        box.append(self.pixel)
        box.append(self.flip)
        row = Gtk.Box(spacing=8)
        self.name = Gtk.Entry(text=name, hexpand=True)
        row.append(self.name)
        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda *_: self._save())
        row.append(save)
        box.append(row)
        self.set_child(box)

    def _draw(self, area, cr, w, h):
        _checker(cr, 0, 0, w, h, 10)
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

    def _click(self, gesture, n, x, y):
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
    if m["pixel"] and surf.get_width() <= GRID_W and surf.get_height() <= GRID_H:
        PixelEditor(app, on_saved, name).present()
    else:
        HotspotPicker(app, on_saved, name, surf, editing=True).present()
