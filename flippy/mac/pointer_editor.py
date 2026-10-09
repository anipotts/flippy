"""Make custom pointers on macOS: a pixel-art canvas, and image import with a hotspot picker.

The AppKit counterpart of flippy/linux/pointer_editor.py; the pixel model is
shared (flippy/pixelart.py). On save they call on_saved(name).
"""
import colorsys
import math
import re

import cairo
from AppKit import (NSAlert, NSApp, NSAppearance, NSBackingStoreBuffered, NSOpenPanel, NSTextField, NSWindow,
                    NSWindowStyleMaskClosable, NSWindowStyleMaskTitled, NSColorSpace)
from Foundation import NSMakeRect
from PIL import Image

from .. import pointers
from ..pixelart import CELL, GRID_H, GRID_W, PALETTE, PixelArt, checker
from . import setup_style as style
from .cairoview import cairo_view
from .setup_style import button
from .widgets import FlippedView, label, target

_open = []  # keep editor windows alive while they're up


def _window(title, w, h):
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, w, h), NSWindowStyleMaskTitled | NSWindowStyleMaskClosable, NSBackingStoreBuffered, False)
    win.setTitle_(title)
    win.setReleasedWhenClosed_(False)
    win.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
    win.setBackgroundColor_(style.color(style.BACKGROUND))
    win.center()
    content = style.panel(w, h)  # flipped, painted black
    win.setContentView_(content)
    return win, content


def checkbox(title, on, fn, keep):
    """The outlined square checkbox with its title beside it (clicking the title doesn't toggle)."""
    box = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 220, 22))
    box.addSubview_(style.check(on, fn, keep))
    lab = label(title, 12)
    lab.setFrameOrigin_((30, (22 - lab.frame().size.height) / 2))
    box.addSubview_(lab)
    return box


def to_hex(rgb):
    return "#" + "".join(f"{round(max(0, min(c, 1)) * 255):02X}" for c in rgb)


def from_hex(text):
    """'#RGB', '#RRGGBB' or without the # -> (r, g, b) 0-1, else None."""
    text = text.strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{3}", text):
        text = "".join(c * 2 for c in text)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        return None
    return tuple(int(text[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _place(parent, view, x, y, w=None, h=None):
    f = view.frame()
    view.setFrame_(NSMakeRect(x, y, w or f.size.width, h or f.size.height))
    parent.addSubview_(view)
    return view


def _name_field(text, width=220):
    """(the outlined box to place, the field inside it)"""
    field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, width, 24))
    field.setStringValue_(text)
    return style.outline_field(field, width), field


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
        self.tools = []
        bx = x
        for title, key, tip in (("Pencil", "pencil", "Click paints, right-click (or ⌃-click) erases"),
                                ("Fill", "fill", "Fill an area"),
                                ("Tip", "hotspot", "Click the pixel that should touch the target")):
            b = button(title, lambda key=key: self._set_tool(key), self.keep)
            b.setToolTip_(tip)
            b.setAccessibilityRole_("AXRadioButton")
            _place(root, b, bx, y)
            bx += b.frame().size.width - 1
            self.tools.append((key, b))
        undo = button("Undo", self._undo, self.keep)
        _place(root, undo, x + side_w - undo.frame().size.width, y)
        self._set_tool("pencil")
        y += 36
        _place(root, checkbox("Mirror ↔", False, self._set_mirror, self.keep), x, y)
        y += 34

        _place(root, label("Color", 13, bold=True), x, y)
        y += 22
        self.swatches = []
        for i, col in enumerate(PALETTE):
            sw = cairo_view(NSMakeRect(0, 0, 30, 30), lambda cr, w, h, c=col: self._swatch(cr, w, h, c),
                            on_press=lambda *_, c=col: self._pick(c))
            if col is None:
                sw.setToolTip_("Eraser (transparent)")
            self.swatches.append(_place(root, sw, x + (i % 6) * 36, y + (i // 6) * 36))
        y += 2 * 36 + 6
        # the chosen color, its hex code, and the eyedropper
        self.current = _place(root, cairo_view(NSMakeRect(0, 0, 44, 26),
                                               lambda cr, w, h: self._swatch(cr, w, h, self.color, True)), x, y)
        hex_box, self.hex = _name_field(to_hex(self.color), 96)
        self.hex.setPlaceholderString_("#RRGGBB")
        self.hex.setAccessibilityLabel_("Hex color")
        t = target(lambda field: self._typed_hex())
        self.keep.append(t)
        self.hex.setTarget_(t)
        self.hex.setAction_("fire:")
        _place(root, hex_box, x + 52, y)
        dropper = button("Eyedropper", self._eyedropper, self.keep)
        dropper.setToolTip_("Pick a color from anywhere on the screen")
        _place(root, dropper, x + side_w - dropper.frame().size.width, y)
        y += 36
        # hue, saturation, brightness, or (the RGB button) red, green, blue 0-255
        self.hsv = colorsys.rgb_to_hsv(*self.color)
        self.mode = "hsb"
        self.sliders, self.letters, self.values = [], [], []
        for i in range(3):
            self.letters.append(_place(root, label("H", 11, color=style.color(style.MUTED)), x, y + 2, 16))
            sl = cairo_view(NSMakeRect(0, 0, side_w - 22 - 40, 20),
                            lambda cr, w, h, i=i: self._draw_slider(cr, w, h, i),
                            on_press=lambda px, py, right, i=i: self._slide(i, px),
                            on_drag=lambda px, py, i=i: self._slide(i, px))
            self.sliders.append(_place(root, sl, x + 22, y))
            self.values.append(_place(root, label("000", 11), x + side_w - 34, y + 2, 34))
            y += 26
        self.mode_button = button("RGB", self._toggle_mode, self.keep)
        self.mode_button.setToolTip_("Switch between hue/saturation/brightness and red/green/blue (0-255) sliders")
        _place(root, self.mode_button, x + side_w - self.mode_button.frame().size.width, y + 2)
        self._show_mode()
        y += 34
        y += 10

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

        name_box, self.name = _name_field(name or pointers.unique_name("My pointer"), side_w)
        _place(root, name_box, x, y)
        y += 34
        self.flip = pointers.meta(name)["flip"] if name else True
        _place(root, checkbox("Flip near bottom", self.flip, lambda on: setattr(self, "flip", on), self.keep), x, y + 2)
        save = button("Save", self._save, self.keep, primary=True)
        _place(root, save, x + side_w - save.frame().size.width, y)
        self.win.setContentSize_((cw + 340, max(ch + 32, y + 44)))  # the side column is taller than the canvas

    # ---- tools
    def _set_mirror(self, on):
        self.mirror = on
        self._redraw()

    def _set_tool(self, key):
        self.tool = key
        for k, b in self.tools:
            b.set_selected(k == key)

    def _pick(self, color, keep_hsv=False):
        self.color = color
        if color is not None:
            if not keep_hsv:
                self.hsv = colorsys.rgb_to_hsv(*color)
            if self.win.firstResponder() is not self.hex.currentEditor():
                self.hex.setStringValue_(to_hex(color))
        for view in self.swatches + self.sliders + [self.current]:
            view.setNeedsDisplay_(True)
        self._show_values()

    def _typed_hex(self):
        rgb = from_hex(str(self.hex.stringValue()))
        if rgb is None:
            self.hex.setStringValue_(to_hex(self.color) if self.color else "")
            return
        self.hex.setStringValue_(to_hex(rgb))
        self._pick(rgb)

    def _eyedropper(self):
        from AppKit import NSColorSampler

        def picked(color):
            if color is not None:
                c = color.colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
                self._pick((c.redComponent(), c.greenComponent(), c.blueComponent()))
        self.sampler = NSColorSampler.alloc().init()  # kept while it's up
        self.sampler.showSamplerWithSelectionHandler_(picked)

    def _toggle_mode(self):
        self.mode = "rgb" if self.mode == "hsb" else "hsb"
        self._show_mode()

    def _show_mode(self):
        names = ("Red", "Green", "Blue") if self.mode == "rgb" else ("Hue", "Saturation", "Brightness")
        for letter, sl, name in zip(self.letters, self.sliders, names):
            letter.setStringValue_(name[0])
            sl.setAccessibilityLabel_(name)
            sl.setNeedsDisplay_(True)
        self.mode_button.setTitle_("HSB" if self.mode == "rgb" else "RGB")
        self._show_values()

    def _rgb(self):
        return self.color if self.color is not None else colorsys.hsv_to_rgb(*self.hsv)

    def _show_values(self):
        if self.mode == "rgb":
            texts = [str(round(c * 255)) for c in self._rgb()]
        else:
            h, s_, v = self.hsv
            texts = [f"{round(h * 360)}°", f"{round(s_ * 100)}%", f"{round(v * 100)}%"]
        for view, text in zip(self.values, texts):
            view.setStringValue_(text)

    def _slide(self, i, px):
        w = self.sliders[i].frame().size.width
        frac = max(0.0, min((px - 7) / (w - 14), 1.0))
        if self.mode == "rgb":
            rgb = list(self._rgb())
            rgb[i] = round(frac * 255) / 255  # whole 0-255 steps
            self._pick(tuple(rgb))
            return
        hsv = list(self.hsv)
        hsv[i] = frac
        self.hsv = tuple(hsv)
        self._pick(colorsys.hsv_to_rgb(*self.hsv), keep_hsv=True)

    def _draw_slider(self, cr, w, h, i):
        """A gradient track (the hue spectrum, or this color from gray / from black) with the pill knob."""
        hue, sat, val = self.hsv
        track = cairo.LinearGradient(7, 0, w - 7, 0)
        if self.mode == "rgb":  # this color with the channel at 0 .. at 255
            rgb = self._rgb()
            for f in (0, 1):
                track.add_color_stop_rgb(f, *[f if k == i else c for k, c in enumerate(rgb)])
            at = rgb[i]
        else:
            for k in range(13 if i == 0 else 2):
                f = k / (12 if i == 0 else 1)
                hsv = (f, 1, 1) if i == 0 else ((hue, f, val) if i == 1 else (hue, sat, f))
                track.add_color_stop_rgb(f, *colorsys.hsv_to_rgb(*hsv))
            at = self.hsv[i]
        cr.rectangle(7, h / 2 - 4, w - 14, 8)
        cr.set_source(track)
        cr.fill_preserve()
        cr.set_source_rgb(*style.OUTLINE)
        cr.set_line_width(1)
        cr.stroke()
        kx = 7 + (w - 14) * at
        cr.rectangle(kx - 4, 1, 8, h - 2)  # a sharp knob, like the rest of the window
        cr.set_source_rgb(*style.TEXT)
        cr.fill_preserve()
        cr.set_source_rgb(0, 0, 0)
        cr.stroke()

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

    def _swatch(self, cr, w, h, col, current=False):
        self._fill_swatch(cr, w, h, col)
        chosen = current or col == self.color
        cr.rectangle(0.5, 0.5, w - 1, h - 1)
        cr.set_source_rgb(*(style.TEXT if chosen and not current else style.OUTLINE))
        cr.set_line_width(2 if chosen and not current else 1)
        cr.stroke()

    @staticmethod
    def _fill_swatch(cr, w, h, col):
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
        name_box, self.name = _name_field(name, 300)
        _place(root, name_box, 16, y)
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

