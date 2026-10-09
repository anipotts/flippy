"""Draw Flippy's app icon (the black-and-white pixel hand with white click lines, no tile) and build Flippy.icns.

Usage: python packaging/macos/make_icon.py <out.icns>
"""
import math
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
    # no tile or border: the hand and its click lines fill the macOS icon grid's 824px area
    rows, px = themes.HAND, 30  # one sprite pixel = a 30px block
    w, h = len(rows[0]) * px, len(rows) * px
    rays = 0.34 * h  # how far the click lines reach above the fingertip
    ox, oy = round((1024 - w) / 2), round((1024 - (h + rays)) / 2 + rays)
    cr.set_antialias(cairo.ANTIALIAS_NONE)  # no seams between the blocks
    for dx, dy, shadow in ((8, 12, True), (0, 0, False)):
        for r, row in enumerate(rows):
            for c, ch in enumerate(row):
                if ch == " ":
                    continue
                if shadow:
                    cr.set_source_rgba(0, 0, 0, 0.3)
                else:
                    cr.set_source_rgb(*((0, 0, 0) if ch == "#" else (1, 1, 1)))
                cr.rectangle(ox + c * px + dx, oy + r * px + dy, px, px)
                cr.fill()
    cr.set_antialias(cairo.ANTIALIAS_DEFAULT)
    # white click lines off the fingertip, edged in black like the hand so they show on a light Dock too
    tip_x, tip_y = ox + (themes.HAND_TIP_COL + 0.5) * px, oy
    start, length = 0.15 * h, 0.19 * h
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for color, width in (((0, 0, 0), 0.075 * h + 2 * px * 0.6), ((1, 1, 1), 0.075 * h)):
        cr.set_source_rgb(*color)
        cr.set_line_width(width)
        for a in (-90, -130, -50, -165, -15):
            r = math.radians(a)
            cr.move_to(tip_x + start * math.cos(r), tip_y + start * math.sin(r))
            cr.line_to(tip_x + (start + length) * math.cos(r), tip_y + (start + length) * math.sin(r))
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
