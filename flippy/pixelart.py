"""The pointer editor's model, shared by the GTK and AppKit editors: grid, tools, undo, load/save.

Two ways to draw: pixel art on the GRID_W x GRID_H grid (cells), or smooth (a normal drawing: round brush
strokes on a canvas RES times finer than the grid). Either way the tip (hotspot) is a grid cell, and the
pointer shows at the same size.
"""
import colorsys
import math
import re

import cairo

from . import pointers, themes

GRID_W, GRID_H = 20, 24
CELL = 18
RES = 16                    # smooth drawing: canvas pixels per grid cell
BRUSHES = (6, 12, 24)       # smooth brush widths, in canvas pixels (thin, medium, thick)
PALETTE = [None, (0, 0, 0), (1, 1, 1), (0.55, 0.55, 0.6), (1.0, 0.25, 0.2), (1.0, 0.6, 0.1), (1.0, 0.9, 0.2),
           (0.2, 0.85, 0.35), (0.25, 0.6, 1.0), (0.6, 0.35, 0.95), (1.0, 0.5, 0.75), (0.55, 0.35, 0.2)]


def checker(cr, x, y, w, h, sq=6):
    cr.set_source_rgb(0.32, 0.32, 0.35)
    cr.rectangle(x, y, w, h)
    cr.fill()
    cr.set_source_rgb(0.42, 0.42, 0.45)
    for j in range(int(h // sq) + 1):
        for i in range(int(w // sq) + 1):
            if (i + j) % 2:
                cr.rectangle(x + i * sq, y + j * sq, min(sq, w - i * sq), min(sq, h - j * sq))
    cr.fill()


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


# ---- the editor's color sliders: hue / saturation / brightness, or red / green / blue in whole 0-255 steps
def slide(mode, channel, frac, rgb, hsv):
    """Slider `channel` moved to frac (0-1): the new (rgb, hsv). In HSB the hue and saturation stay where they were
    set even at black or gray, where the color alone would lose them."""
    frac = max(0.0, min(frac, 1.0))
    if mode == "rgb":
        rgb = tuple(round(frac * 255) / 255 if k == channel else c for k, c in enumerate(rgb))
        return rgb, colorsys.rgb_to_hsv(*rgb)
    hsv = tuple(frac if k == channel else c for k, c in enumerate(hsv))
    return colorsys.hsv_to_rgb(*hsv), hsv


def slider_at(mode, channel, rgb, hsv):
    """Where slider `channel`'s knob sits, 0-1."""
    return rgb[channel] if mode == "rgb" else hsv[channel]


def slider_texts(mode, rgb, hsv):
    """The values shown beside the sliders: "0".."255", or "360°", "100%", "100%"."""
    if mode == "rgb":
        return [str(round(c * 255)) for c in rgb]
    h, s, v = hsv
    return [f"{round(h * 360)}°", f"{round(s * 100)}%", f"{round(v * 100)}%"]


def from_sprite(grid_rows, tip_col):
    """Built-in sprite (# outline . fill) -> centered grid + hotspot."""
    cells = [[None] * GRID_W for _ in range(GRID_H)]
    ox = (GRID_W - len(grid_rows[0])) // 2
    oy = (GRID_H - len(grid_rows)) // 2
    for r, row in enumerate(grid_rows):
        for c, ch in enumerate(row):
            if ch != " ":
                cells[oy + r][ox + c] = (0, 0, 0) if ch == "#" else (1, 1, 1)
    return cells, (ox + tip_col, oy)


def _blank_smooth():
    return cairo.ImageSurface(cairo.FORMAT_ARGB32, GRID_W * RES, GRID_H * RES)


def _copy(surf):
    out = _blank_smooth()
    cr = cairo.Context(out)
    cr.set_source_surface(surf)
    cr.paint()
    return out


class PixelArt:
    def __init__(self, name=None):
        self.cells = [[None] * GRID_W for _ in range(GRID_H)]
        self.smooth = None        # a cairo surface when drawing smooth; None = pixel art
        self.brush = BRUSHES[1]
        self.last = None          # the previous point of a smooth stroke
        self.hotspot = (GRID_W // 2, 0)
        self.undo_stack = []
        if name:
            self.load(name)

    @property
    def pixel(self):
        return self.smooth is None

    def snapshot(self):
        self.undo_stack.append(([row[:] for row in self.cells], None if self.pixel else _copy(self.smooth),
                                self.hotspot))
        self.undo_stack = self.undo_stack[-50:]

    def undo(self):
        if self.undo_stack:
            self.cells, self.smooth, self.hotspot = self.undo_stack.pop()  # mode included

    def set_pixel(self, pixel):
        """Switch modes, keeping the drawing: cells become blocks on the canvas, or the canvas is sampled per cell."""
        if pixel == self.pixel:
            return
        self.snapshot()
        if pixel:
            self.cells = self._smooth_to_cells()
            self.smooth = None
        else:
            self.smooth = self._cells_to_smooth()

    def _cells_to_smooth(self):
        surf = _blank_smooth()
        cr = cairo.Context(surf)
        cr.set_antialias(cairo.ANTIALIAS_NONE)
        for y, row in enumerate(self.cells):
            for x, c in enumerate(row):
                if c is not None:
                    cr.set_source_rgb(*c)
                    cr.rectangle(x * RES, y * RES, RES, RES)
                    cr.fill()
        surf.flush()
        return surf

    def _smooth_to_cells(self):
        self.smooth.flush()
        data, stride = self.smooth.get_data(), self.smooth.get_stride()
        cells = [[None] * GRID_W for _ in range(GRID_H)]
        for cy in range(GRID_H):
            for cx in range(GRID_W):
                i = (cy * RES + RES // 2) * stride + (cx * RES + RES // 2) * 4
                b, g, r, a = data[i:i + 4]
                if a > 127:
                    cells[cy][cx] = (r / a, g / a, b / a)
        return cells

    def blank(self):
        self.snapshot()
        self.cells = [[None] * GRID_W for _ in range(GRID_H)]
        if not self.pixel:
            self.smooth = _blank_smooth()

    def start(self, kind):
        self.snapshot()
        rows, tip = (themes.HAND, themes.HAND_TIP_COL) if kind == "hand" else (themes.ARROW, 0)
        self.cells, self.hotspot = from_sprite(rows, tip)
        if not self.pixel:
            self.smooth = self._cells_to_smooth()

    def load(self, name):
        surf = pointers.surface(name)
        if surf is None:
            return
        m = pointers.meta(name)
        if not m["pixel"] and (surf.get_width(), surf.get_height()) == (GRID_W * RES, GRID_H * RES):
            self.smooth = _copy(surf)  # a smooth drawing made here
            self.hotspot = (m["hotspot"][0] // RES, m["hotspot"][1] // RES)
            return
        w, h = min(surf.get_width(), GRID_W), min(surf.get_height(), GRID_H)
        data, stride = surf.get_data(), surf.get_stride()
        for yy in range(h):
            for xx in range(w):
                b, g, r, a = data[yy * stride + xx * 4: yy * stride + xx * 4 + 4]
                if a > 127:  # premultiplied ARGB32, little-endian -> BGRA bytes
                    self.cells[yy][xx] = (r / a, g / a, b / a)
        self.hotspot = tuple(pointers.meta(name)["hotspot"])

    @staticmethod
    def cell_at(x, y):
        cx, cy = int(x // CELL), int(y // CELL)
        return (cx, cy) if 0 <= cx < GRID_W and 0 <= cy < GRID_H else None

    # ---- smooth drawing (canvas coordinates: the editor's on-screen px; CELL of them per grid cell)
    def stroke_to(self, x, y, color, mirror=False):
        """Continue the stroke to (x, y); color None erases. Call end_stroke() when the button lifts."""
        k = RES / CELL
        point = (x * k, y * k)
        start = self.last or point
        cr = cairo.Context(self.smooth)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_line_width(self.brush)
        if color is None:
            cr.set_operator(cairo.OPERATOR_CLEAR)
        else:
            cr.set_source_rgb(*color)
        for flip in ((False, True) if mirror else (False,)):
            fx = (lambda v: GRID_W * RES - v) if flip else (lambda v: v)
            cr.move_to(fx(start[0]), start[1])
            cr.line_to(fx(point[0]) + (0.01 if point == start else 0), point[1])  # a dot for a click
            cr.stroke()
        self.smooth.flush()
        self.last = point

    def end_stroke(self):
        self.last = None

    def fill_smooth(self, x, y, color):
        """Flood fill the area under (x, y) (canvas px) by color and coverage, tolerant of soft brush edges."""
        k = RES / CELL
        sx, sy = int(x * k), int(y * k)
        W, H = GRID_W * RES, GRID_H * RES
        if not (0 <= sx < W and 0 <= sy < H):
            return
        self.smooth.flush()
        data, stride = self.smooth.get_data(), self.smooth.get_stride()
        at = lambda px, py: bytes(data[py * stride + px * 4: py * stride + px * 4 + 4])
        target = at(sx, sy)
        new = bytes((0, 0, 0, 0)) if color is None else bytes(
            (round(color[2] * 255), round(color[1] * 255), round(color[0] * 255), 255))
        if target == new:
            return
        close = lambda p: all(abs(a - b) <= 48 for a, b in zip(p, target))
        seen, stack = set(), [(sx, sy)]
        while stack:
            px, py = stack.pop()
            if (px, py) in seen or not (0 <= px < W and 0 <= py < H) or not close(at(px, py)):
                continue
            seen.add((px, py))
            i = py * stride + px * 4
            data[i:i + 4] = new
            stack += [(px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)]
        self.smooth.mark_dirty()

    def paint(self, cell, color, mirror=False):
        cx, cy = cell
        self.cells[cy][cx] = color
        if mirror:
            self.cells[cy][GRID_W - 1 - cx] = color

    def fill(self, cell, color):
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

    def surface(self):
        if not self.pixel:
            return _copy(self.smooth)
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

    def draw_canvas(self, cr, w, h, mirror=False):
        checker(cr, 0, 0, w, h, CELL / 2)
        if not self.pixel:
            cr.save()
            cr.scale(CELL / RES, CELL / RES)
            pat = cairo.SurfacePattern(self.smooth)
            pat.set_filter(cairo.FILTER_GOOD)
            cr.set_source(pat)
            cr.paint()
            cr.restore()
        for y in range(GRID_H if self.pixel else 0):
            for x in range(GRID_W):
                c = self.cells[y][x]
                if c is not None:
                    cr.set_source_rgb(*c)
                    cr.rectangle(x * CELL, y * CELL, CELL, CELL)
                    cr.fill()
        cr.set_source_rgba(0, 0, 0, 0.18 if self.pixel else 0.08)  # the grid stays: the tip snaps to it
        cr.set_line_width(1)
        for x in range(GRID_W + 1):
            cr.move_to(x * CELL + 0.5, 0)
            cr.line_to(x * CELL + 0.5, h)
        for y in range(GRID_H + 1):
            cr.move_to(0, y * CELL + 0.5)
            cr.line_to(w, y * CELL + 0.5)
        cr.stroke()
        if mirror:
            cr.set_source_rgba(0.3, 0.7, 1.0, 0.6)
            cr.move_to(GRID_W * CELL / 2, 0)
            cr.line_to(GRID_W * CELL / 2, h)
            cr.stroke()
        hx, hy = self.hotspot  # the tip: red circle
        cx, cy = hx * CELL + CELL / 2, hy * CELL + CELL / 2
        cr.set_source_rgb(1, 0.2, 0.2)
        cr.set_line_width(2)
        cr.arc(cx, cy, CELL * 0.45, 0, 2 * math.pi)
        cr.stroke()

    def draw_preview(self, cr, w, h):
        """The pointer at real size on a dark and a light background."""
        surf = self.surface()
        px = themes.sprite_px(1.0) / (1 if self.pixel else RES)
        hx, hy = self.hotspot if self.pixel else self._smooth_hotspot()
        for i, bg in enumerate(((0.12, 0.12, 0.14), (0.92, 0.92, 0.94))):
            cr.set_source_rgb(*bg)
            cr.rectangle(i * w / 2, 0, w / 2, h)
            cr.fill()
            cr.save()
            cr.translate(i * w / 2 + w / 4 - hx * px, 10 - hy * px)
            cr.scale(px, px)
            pat = cairo.SurfacePattern(surf)
            pat.set_filter(cairo.FILTER_NEAREST if self.pixel else cairo.FILTER_GOOD)
            cr.set_source(pat)
            cr.paint()
            cr.restore()

    def _smooth_hotspot(self):
        """The tip cell's center on the smooth canvas."""
        return self.hotspot[0] * RES + RES // 2, self.hotspot[1] * RES + RES // 2

    def save(self, name, editing=None, flip=True):
        name = name.strip() or "My pointer"
        if editing and name != editing:
            pointers.delete(editing)
        if self.pixel:
            pointers.save(name, self.surface(), self.hotspot, pixel=True, flip=flip)
        else:
            pointers.save(name, self.surface(), self._smooth_hotspot(), pixel=False, flip=flip, grid_h=GRID_H)
        return name


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


def demo_paint(art, redraw, set_tool, set_color, on_done, cell_ms=34):
    """Paint DEMO_SPRITE into `art` like a person would, then call on_done()."""
    from . import loop
    ox, oy = 1, 1
    cells = {k: [(ox + c, oy + r) for r, row in enumerate(DEMO_SPRITE) for c, ch in enumerate(row) if ch == k]
             for k in "ohs"}
    steps = [("tool", "pencil"), ("color", "o")] + [("paint", xy) for xy in cells["o"]]
    steps += [("pause", 6), ("tool", "fill"), ("color", "f"), ("pause", 4), ("fill", (ox + 2, oy + 6)), ("pause", 8),
              ("tool", "pencil"), ("color", "h")] + [("paint", xy) for xy in cells["h"]]
    steps += [("color", "s")] + [("paint", xy) for xy in cells["s"]]
    steps += [("pause", 6), ("tool", "hotspot"), ("pause", 4), ("tip", (ox, oy)), ("pause", 16), ("done", None)]
    it = iter(steps)
    color = [None]

    def tick():
        try:
            kind, arg = next(it)
        except StopIteration:
            return False
        if kind == "pause":  # wait `arg` ticks, then carry on
            loop.timeout_add(cell_ms * arg, lambda: loop.timeout_add(cell_ms, tick) and False)
            return False
        if kind == "tool":
            set_tool(arg)
        elif kind == "color":
            color[0] = DEMO_COLORS[arg]
            set_color(color[0])
        elif kind == "paint":
            art.snapshot()
            art.paint(arg, color[0])
        elif kind == "fill":
            art.snapshot()
            art.fill(arg, color[0])
        elif kind == "tip":
            art.snapshot()
            art.hotspot = arg
        elif kind == "done":
            on_done()
            return False
        redraw()
        return True
    loop.timeout_add(700, lambda: loop.timeout_add(cell_ms, tick) and False)
