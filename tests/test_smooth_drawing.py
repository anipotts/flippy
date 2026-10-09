"""Smooth (non-pixel) pointer drawings in the editor's model (flippy/pixelart.py): strokes, fill, switching
styles, undo, and saving at the pixel grid's size with the tip on a grid cell."""
import os
import tempfile
import unittest
from unittest.mock import patch

from flippy import pointers
from flippy.pixelart import CELL, GRID_H, GRID_W, RES, PixelArt


def alpha_at(art, x, y):  # canvas px (the editor's) -> the smooth surface's alpha there
    surf = art.smooth
    surf.flush()
    i = int(y * RES / CELL) * surf.get_stride() + int(x * RES / CELL) * 4
    return surf.get_data()[i + 3]


class Smooth(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for attr, value in (("DIR", d.name), ("INDEX", os.path.join(d.name, "index.json"))):
            p = patch.object(pointers, attr, value)
            p.start()
            self.addCleanup(p.stop)
        pointers._cache.clear()

    def test_a_stroke_paints_and_right_click_erases(self):
        art = PixelArt()
        art.set_pixel(False)
        art.stroke_to(40, 40, (1, 1, 1))
        art.stroke_to(120, 40, (1, 1, 1))
        art.end_stroke()
        self.assertEqual(alpha_at(art, 80, 40), 255)
        self.assertEqual(alpha_at(art, 80, 120), 0)
        art.stroke_to(80, 40, None)
        art.end_stroke()
        self.assertEqual(alpha_at(art, 80, 40), 0)

    def test_switching_keeps_the_drawing_and_undo_switches_back(self):
        art = PixelArt()
        art.start("hand")
        filled = sum(c is not None for row in art.cells for c in row)
        art.set_pixel(False)
        self.assertFalse(art.pixel)
        art.set_pixel(True)
        self.assertEqual(sum(c is not None for row in art.cells for c in row), filled)
        art.undo()
        self.assertFalse(art.pixel)

    def test_fill_covers_the_area(self):
        art = PixelArt()
        art.set_pixel(False)
        art.fill_smooth(5, 5, (1, 0, 0))
        self.assertEqual(alpha_at(art, GRID_W * CELL - 2, GRID_H * CELL - 2), 255)

    def test_saved_at_grid_size_with_the_tip_on_a_cell_and_reopens_smooth(self):
        art = PixelArt()
        art.set_pixel(False)
        art.stroke_to(50, 50, (0, 0, 0))
        art.end_stroke()
        art.hotspot = (3, 2)
        name = art.save("Doodle")
        m = pointers.meta(name)
        self.assertFalse(m["pixel"])
        self.assertEqual(m["grid_h"], GRID_H)
        self.assertEqual(m["hotspot"], [3 * RES + RES // 2, 2 * RES + RES // 2])
        surf = pointers.surface(name)
        # shown as tall as a pixel pointer of the same grid
        self.assertAlmostEqual(pointers._scale(surf, m, 1.0, 4) * surf.get_height(), 4 * GRID_H)
        again = PixelArt(name)
        self.assertFalse(again.pixel)
        self.assertEqual(again.hotspot, (3, 2))

    def test_pixel_art_still_saves_as_pixels(self):
        art = PixelArt()
        art.start("arrow")
        m = pointers.meta(art.save("Arrowish"))
        self.assertTrue(m["pixel"])
        self.assertIsNone(m["grid_h"])


if __name__ == "__main__":
    unittest.main()
