"""Make custom pointers on macOS: a pixel-art canvas, and image import with a hotspot picker.

The AppKit counterpart of flippy/linux/pointer_editor.py; the pixel model is
shared (flippy/pixelart.py). On save they call on_saved(name).
"""
import math

import cairo
from AppKit import (NSAlert, NSApp, NSBackingStoreBuffered, NSColorWell, NSOpenPanel, NSSegmentedControl,
                    NSTextField, NSWindow, NSWindowStyleMaskClosable, NSWindowStyleMaskTitled, NSColorSpace)
from Foundation import NSMakeRect
from PIL import Image

from .. import pointers
from ..pixelart import CELL, GRID_H, GRID_W, PALETTE, PixelArt, checker
from .cairoview import cairo_view
from .widgets import FlippedView, button, checkbox, label, target

_open = []  # keep editor windows alive while they're up


def _window(title, w, h):
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, w, h), NSWindowStyleMaskTitled | NSWindowStyleMaskClosable, NSBackingStoreBuffered, False)
    win.setTitle_(title)
    win.setReleasedWhenClosed_(False)
    win.center()
    content = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
    win.setContentView_(content)
    return win, content


def _place(parent, view, x, y, w=None, h=None):
    f = view.frame()
    view.setFrame_(NSMakeRect(x, y, w or f.size.width, h or f.size.height))
    parent.addSubview_(view)
    return view


def _name_field(text):
    field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 220, 24))
    field.setStringValue_(text)
    return field


class _Editor:
    def present(self):
        _open.append(self)
        NSApp.activateIgnoringOtherApps_(True)
        self.win.makeKeyAndOrderFront_(None)

    def close(self):
        self.win.close()
        if self in _open:
            _open.remove(self)


class PixelEditor(_Editor):
    def __init__(self, on_saved, name=None):
        self.on_saved = on_saved
        self.editing = name
        self.art = PixelArt(name)
        self.color = (0, 0, 0)
        self.tool = "pencil"
        self.mirror = False
        self.erasing = False
        self.keep = []
        cw, ch = GRID_W * CELL, GRID_H * CELL
        self.win, root = _window("Draw a pointer", cw + 340, ch + 32)

        self.canvas = _place(root, cairo_view(NSMakeRect(0, 0, cw, ch),
                                              lambda cr, w, h: self.art.draw_canvas(cr, w, h, self.mirror),
                                              on_press=self._press, on_drag=self._drag), 16, 16)
        x, y, side_w = cw + 32, 16, 292
        _place(root, label("Tools", 13, bold=True), x, y)
        y += 22
        seg = NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
            ["Pencil", "Fill", "Tip"], 0, None, None)
        self.tools = ["pencil", "fill", "hotspot"]
        t = target(lambda s: setattr(self, "tool", self.tools[s.selectedSegment()]))
        self.keep.append(t)
        seg.setTarget_(t)
        seg.setAction_("fire:")
        seg.setSelectedSegment_(0)
        seg.setToolTip_("Pencil: click paints, right-click (or ⌃-click) erases · Fill: fill an area · "
                        "Tip: click the pixel that should touch the target")
        self.seg = _place(root, seg, x, y)
        y += 32
        _place(root, checkbox("Mirror ↔", False, self._set_mirror, self.keep), x, y + 3)
        _place(root, button("Undo", self._undo, self.keep), x + 110, y)
        y += 38

        _place(root, label("Color", 13, bold=True), x, y)
        y += 22
        for i, col in enumerate(PALETTE):
            sw = cairo_view(NSMakeRect(0, 0, 30, 30), lambda cr, w, h, c=col: self._swatch(cr, w, h, c),
                            on_press=lambda *_, c=col: self._pick(c))
            if col is None:
                sw.setToolTip_("Eraser (transparent)")
            _place(root, sw, x + (i % 6) * 36, y + (i // 6) * 36)
        y += 2 * 36 + 4
        _place(root, label("Custom:", 12), x, y + 4)
        well = NSColorWell.alloc().initWithFrame_(NSMakeRect(0, 0, 44, 24))
        t = target(lambda s: self._pick_well(s))
        self.keep.append(t)
        well.setTarget_(t)
        well.setAction_("fire:")
        _place(root, well, x + 60, y)
        y += 38

        _place(root, label("Start from", 13, bold=True), x, y)
        y += 22
        bx = x
        for title, fn in (("Blank", lambda: self._do(self.art.blank)), ("Hand", lambda: self._do(self.art.start, "hand")),
                          ("Arrow", lambda: self._do(self.art.start, "arrow"))):
            b = _place(root, button(title, fn, self.keep), bx, y)
            bx += b.frame().size.width + 6
        y += 38

        _place(root, label("Preview", 13, bold=True), x, y)
        y += 22
        self.preview = _place(root, cairo_view(NSMakeRect(0, 0, side_w, 110), self.art.draw_preview), x, y)
        y += 110 + 16

        self.name = _place(root, _name_field(name or pointers.unique_name("My pointer")), x, y, side_w)
        y += 34
        self.flip = pointers.meta(name)["flip"] if name else True
        _place(root, checkbox("Flip near bottom", self.flip, lambda on: setattr(self, "flip", on), self.keep), x, y + 4)
        save = button("Save", self._save, self.keep, primary=True)
        _place(root, save, x + side_w - save.frame().size.width, y)
        self.win.setContentSize_((cw + 340, max(ch + 32, y + 44)))  # the side column is taller than the canvas

    # ---- tools
    def _set_mirror(self, on):
        self.mirror = on
        self._redraw()

    def _pick(self, color):
        self.color = color

    def _pick_well(self, well):
        c = well.color().colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
        self.color = (c.redComponent(), c.greenComponent(), c.blueComponent())

    def _do(self, fn, *args):
        fn(*args)
        self._redraw()

    def _undo(self):
        self._do(self.art.undo)

    def _press(self, x, y, right):
        cell = self.art.cell_at(x, y)
        if not cell:
            return
        self.art.snapshot()
        self.erasing = right
        color = None if right else self.color
        if self.tool == "hotspot":
            self.art.hotspot = cell
        elif self.tool == "fill":
            self.art.fill(cell, color)
        else:
            self.art.paint(cell, color, self.mirror)
        self._redraw()

    def _drag(self, x, y):
        if self.tool != "pencil":
            return
        cell = self.art.cell_at(x, y)
        if cell:
            self.art.paint(cell, None if self.erasing else self.color, self.mirror)
            self._redraw()

    def _redraw(self):
        self.canvas.setNeedsDisplay_(True)
        self.preview.setNeedsDisplay_(True)

    @staticmethod
    def _swatch(cr, w, h, col):
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

    def _save(self):
        name = self.art.save(str(self.name.stringValue()), self.editing, self.flip)
        self.on_saved(name)
        self.close()


class HotspotPicker(_Editor):
    """After importing an image: click where it should touch the target."""

    VIEW = 360

    def __init__(self, on_saved, name, surf, editing=False):
        self.on_saved = on_saved
        self.surf = surf
        self.editing = name if editing else None
        self.keep = []
        m = pointers.meta(name) if editing else None
        iw, ih = surf.get_width(), surf.get_height()
        self.k = self.VIEW / max(iw, ih)
        self.hotspot = tuple(m["hotspot"]) if m else (iw // 2, 0)
        self.pixel = m["pixel"] if m else max(iw, ih) <= 48
        self.flip = m["flip"] if m else False
        vw, vh = int(iw * self.k), int(ih * self.k)
        self.win, root = _window("Set the pointer's tip", 420, vh + 200)
        y = 16
        _place(root, label("Click the spot that should touch what Flippy points at.", 13), 16, y)
        y += 28
        self.area = _place(root, cairo_view(NSMakeRect(0, 0, vw, vh), self._draw, on_press=self._click),
                           (420 - vw) / 2, y)
        y += vh + 12
        _place(root, checkbox("Pixel art (keep it crisp)", self.pixel, lambda on: setattr(self, "pixel", on), self.keep), 16, y)
        y += 26
        _place(root, checkbox("Flip near the bottom of the screen", self.flip, lambda on: setattr(self, "flip", on),
                              self.keep), 16, y)
        y += 36
        self.name = _place(root, _name_field(name), 16, y, 300)
        save = button("Save", self._save, self.keep, primary=True)
        _place(root, save, 404 - save.frame().size.width, y - 2)

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
        self.area.setNeedsDisplay_(True)

    def _save(self):
        name = str(self.name.stringValue()).strip() or "Image pointer"
        if self.editing and name != self.editing:
            pointers.delete(self.editing)
        pointers.save(name, self.surf, self.hotspot, pixel=self.pixel, flip=self.flip)
        self.on_saved(name)
        self.close()


def image_surface(path):
    """Load an image (anything Pillow reads), downscale it to MAX_IMPORT_PX, return a cairo ARGB32 surface."""
    im = Image.open(path).convert("RGBA")
    im.thumbnail((pointers.MAX_IMPORT_PX, pointers.MAX_IMPORT_PX), Image.LANCZOS)
    w, h = im.size
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    stride, buf = surf.get_stride(), surf.get_data()
    px = im.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            i = y * stride + x * 4
            buf[i:i + 4] = bytes((b * a // 255, g * a // 255, r * a // 255, a))  # premultiplied BGRA
    surf.mark_dirty()
    return surf


def import_image(on_saved):
    """File picker -> downscale -> hotspot picker."""
    NSApp.activateIgnoringOtherApps_(True)
    panel = NSOpenPanel.openPanel()
    panel.setTitle_("Choose a pointer image")
    panel.setAllowedFileTypes_(["png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff"])
    if panel.runModal() != 1:  # NSModalResponseOK
        return
    path = str(panel.URL().path())
    try:
        surf = image_surface(path)
    except Exception as e:
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Couldn't open that image")
        alert.setInformativeText_(str(e))
        alert.runModal()
        return
    base = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    HotspotPicker(on_saved, pointers.unique_name(base), surf).present()


def edit(on_saved, name):
    """Reopen a custom pointer in the matching editor."""
    m = pointers.meta(name)
    surf = pointers.surface(name)
    if surf is None:
        return
    if m["pixel"] and surf.get_width() <= GRID_W and surf.get_height() <= GRID_H:
        PixelEditor(on_saved, name).present()
    else:
        HotspotPicker(on_saved, name, surf, editing=True).present()

