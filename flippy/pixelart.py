"""The pixel pointer editor's model, shared by the GTK and AppKit editors: grid, tools, undo, load/save."""
import math

import cairo

from . import pointers, themes

GRID_W, GRID_H = 20, 24
CELL = 18
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


class PixelArt:
    def __init__(self, name=None):
        self.cells = [[None] * GRID_W for _ in range(GRID_H)]
        self.hotspot = (GRID_W // 2, 0)
        self.undo_stack = []
        if name:
            self.load(name)

    def snapshot(self):
        self.undo_stack.append(([row[:] for row in self.cells], self.hotspot))
        self.undo_stack = self.undo_stack[-50:]

    def undo(self):
        if self.undo_stack:
            self.cells, self.hotspot = self.undo_stack.pop()

    def blank(self):
        self.snapshot()
        self.cells = [[None] * GRID_W for _ in range(GRID_H)]

    def start(self, kind):
        self.snapshot()
        rows, tip = (themes.HAND, themes.HAND_TIP_COL) if kind == "hand" else (themes.ARROW, 0)
        self.cells, self.hotspot = from_sprite(rows, tip)

    def load(self, name):
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

    @staticmethod
    def cell_at(x, y):
        cx, cy = int(x // CELL), int(y // CELL)
        return (cx, cy) if 0 <= cx < GRID_W and 0 <= cy < GRID_H else None

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
        px = themes.sprite_px(1.0)
        hx, hy = self.hotspot
        for i, bg in enumerate(((0.12, 0.12, 0.14), (0.92, 0.92, 0.94))):
            cr.set_source_rgb(*bg)
            cr.rectangle(i * w / 2, 0, w / 2, h)
            cr.fill()
            cr.save()
            cr.translate(i * w / 2 + w / 4 - hx * px, 10 - hy * px)
            cr.scale(px, px)
            pat = cairo.SurfacePattern(surf)
            pat.set_filter(cairo.FILTER_NEAREST)
            cr.set_source(pat)
            cr.paint()
            cr.restore()

    def save(self, name, editing=None, flip=True):
        name = name.strip() or "My pointer"
        if editing and name != editing:
            pointers.delete(editing)
        pointers.save(name, self.surface(), self.hotspot, pixel=True, flip=flip)
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
