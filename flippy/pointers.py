"""Custom pointers: user PNGs (imported images or pixel drawings) plus a hotspot.

Stored in ~/.config/flippy/pointers/<name>.png with metadata in index.json:
  {"<name>": {"hotspot": [x, y], "pixel": true, "flip": true}}
- hotspot: the image pixel that touches the target (fingertip, arrow tip...)
- pixel: pixel art, drawn crisp at the same scale as the built-in sprites; else smooth, ~64px
- flip: mirror vertically when there's no room below the target (like the built-in hand)
A pointer setting value of "custom:<name>" selects one.
"""
import json
import math
import os
import re

import cairo

from .profile import current
DIR = os.path.join(current().config_dir, "pointers")
INDEX = os.path.join(DIR, "index.json")
PREFIX = "custom:"
IMAGE_PX = 64          # long edge of a smooth (non-pixel) pointer at size 1.0
MAX_IMPORT_PX = 128    # imported images are downscaled to this before saving

_cache = {}  # name -> (mtime, surface)


def _index():
    try:
        with open(INDEX) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_index(data):
    os.makedirs(DIR, exist_ok=True)
    tmp = INDEX + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, INDEX)


def path(name):
    return os.path.join(DIR, f"{name}.png")


def names():
    idx = _index()
    return sorted(n for n in idx if os.path.exists(path(n)))


def exists(name):
    return name in _index() and os.path.exists(path(name))


def meta(name):
    m = _index().get(name, {})
    grid_h = m.get("grid_h")
    return {"hotspot": m.get("hotspot", [0, 0]), "pixel": bool(m.get("pixel", True)), "flip": bool(m.get("flip", True)),
            "grid_h": grid_h if type(grid_h) is int and 0 < grid_h <= 256 else None}


def unique_name(base):
    base = re.sub(r"[^a-zA-Z0-9 _-]", "", base).strip() or "pointer"
    taken, name, k = set(_index()), base, 2
    while name in taken:
        name, k = f"{base} {k}", k + 1
    return name


def save(name, surface, hotspot, pixel, flip=True, grid_h=None):
    """Save a cairo ImageSurface as pointer `name` (overwrites). grid_h: a smooth drawing from the editor,
    shown as tall as a pixel pointer of that many rows."""
    os.makedirs(DIR, exist_ok=True)
    surface.write_to_png(path(name))
    idx = _index()
    idx[name] = {"hotspot": [int(hotspot[0]), int(hotspot[1])], "pixel": bool(pixel), "flip": bool(flip)}
    if grid_h and not pixel:
        idx[name]["grid_h"] = int(grid_h)
    _write_index(idx)
    _cache.pop(name, None)


def delete(name):
    idx = _index()
    idx.pop(name, None)
    _write_index(idx)
    _cache.pop(name, None)
    try:
        os.unlink(path(name))
    except OSError:
        pass


def surface(name):
    p = path(name)
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    hit = _cache.get(name)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        surf = cairo.ImageSurface.create_from_png(p)
    except (cairo.Error, OSError):
        return None
    _cache[name] = (mt, surf)
    return surf


def _scale(surf, m, size, sprite_px):
    if m["pixel"]:
        return sprite_px
    if m["grid_h"]:  # drawn smooth in the editor: as tall as the pixel grid would be
        return sprite_px * m["grid_h"] / surf.get_height()
    return IMAGE_PX * size / max(surf.get_width(), surf.get_height())


def extent(name, size, sprite_px):
    """(right, left, below, above) around the hotspot, in px."""
    surf = surface(name)
    if surf is None:
        return 30, 30, 30, 30
    m = meta(name)
    k = _scale(surf, m, size, sprite_px)
    hx, hy = m["hotspot"]
    return (surf.get_width() - hx) * k, hx * k, (surf.get_height() - hy) * k, hy * k


def draw(cr, name, x, y, t, size, sprite_px, screen_h, tap_rgb):
    """Draw pointer `name` with its hotspot at (x, y); same drop/bob/tap animation as the built-ins."""
    surf = surface(name)
    if surf is None:
        return False
    m = meta(name)
    k = _scale(surf, m, size, sprite_px)
    hx, hy = m["hotspot"]
    intro = min(t / 0.3, 1.0)
    drop = -40 * (1 - intro) ** 3
    bob = 3 * math.sin(t * 4) if intro >= 1 else 0
    pulse = 0.5 + 0.5 * math.sin(t * 4)
    cr.set_source_rgba(*tap_rgb, 0.25 + 0.2 * pulse)
    cr.arc(x, y, (10 + 4 * pulse) * size, 0, 2 * math.pi)
    cr.fill()
    flip = m["flip"] and y + (surf.get_height() - hy) * k + 4 > screen_h
    sgn = -1 if flip else 1
    filt = cairo.FILTER_NEAREST if m["pixel"] else cairo.FILTER_GOOD
    for dx, dy, shadow in ((2, 3, True), (0, 0, False)):
        cr.save()
        cr.translate(x + dx, y + dy + sgn * (2 + drop + bob))
        cr.scale(k, sgn * k)
        cr.translate(-hx, -hy)
        pat = cairo.SurfacePattern(surf)
        pat.set_filter(filt)
        if shadow:
            cr.set_source_rgba(0, 0, 0, 0.35)
            cr.mask(pat)
        else:
            cr.set_source(pat)
            cr.paint()
        cr.restore()
    return True
