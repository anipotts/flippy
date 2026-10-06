"""Draw Flippy's app icon (the pixel hand on a midnight tile) and build Flippy.icns.

Usage: python packaging/macos/make_icon.py <out.icns>
"""
import os
import subprocess
import sys
import tempfile

import cairo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from flippy import themes  # noqa: E402


def draw(size):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(s)
    k = size / 1024
    cr.scale(k, k)
    # macOS icon grid: an 824px rounded tile centered on the 1024 canvas
    themes.round_rect(cr, 100, 100, 824, 824, 185)
    g = cairo.LinearGradient(0, 100, 0, 924)
    g.add_color_stop_rgb(0, 0.16, 0.2, 0.36)
    g.add_color_stop_rgb(1, 0.06, 0.06, 0.12)
    cr.set_source(g)
    cr.fill_preserve()
    cr.set_source_rgba(0.35, 0.63, 1.0, 0.55)
    cr.set_line_width(10)
    cr.stroke()
    # the hand sprite, crisp: one sprite pixel = a 27px block
    rows, px = themes.HAND, 27
    w, h = len(rows[0]) * px, len(rows) * px
    ox, oy = (1024 - w) / 2 + 10, (1024 - h) / 2 + 60
    cr.set_antialias(cairo.ANTIALIAS_NONE)  # no seams between the blocks
    for dx, dy, shadow in ((10, 14, True), (0, 0, False)):
        for r, row in enumerate(rows):
            for c, ch in enumerate(row):
                if ch == " ":
                    continue
                if shadow:
                    cr.set_source_rgba(0, 0, 0, 0.35)
                else:
                    cr.set_source_rgb(*((0.04, 0.04, 0.06) if ch == "#" else (1, 1, 1)))
                cr.rectangle(ox + c * px + dx, oy + r * px + dy, px, px)
                cr.fill()
    cr.set_antialias(cairo.ANTIALIAS_DEFAULT)
    # the tap ring at the fingertip
    tip_x = ox + (themes.HAND_TIP_COL + 0.5) * px
    cr.set_source_rgba(0.35, 0.63, 1.0, 0.9)
    cr.set_line_width(14)
    cr.arc(tip_x, oy - 30, 36, 0, 6.2832)
    cr.stroke()
    return s


def main(out):
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "Flippy.iconset")
        os.makedirs(iconset)
        for base in (16, 32, 128, 256, 512):
            draw(base).write_to_png(os.path.join(iconset, f"icon_{base}x{base}.png"))
            draw(base * 2).write_to_png(os.path.join(iconset, f"icon_{base}x{base}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out], check=True)


if __name__ == "__main__":
    main(sys.argv[1])
