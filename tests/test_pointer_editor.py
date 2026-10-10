"""The Draw editor's color controls (flippy/pixelart.py, used by both editors): the hex field and the sliders."""
import colorsys
import sys
import unittest

from flippy import pixelart


class Hex(unittest.TestCase):
    def test_round_trip_and_short_forms(self):
        self.assertEqual(pixelart.to_hex((0.25, 0.6, 1.0)), "#4099FF")
        self.assertEqual(pixelart.from_hex("#4099ff"), (64 / 255, 153 / 255, 1.0))
        self.assertEqual(pixelart.from_hex("fff"), (1.0, 1.0, 1.0))

    def test_junk_is_refused(self):
        for text in ("", "#12345", "zzzzzz", "#1234567"):
            self.assertIsNone(pixelart.from_hex(text))

    @unittest.skipUnless(sys.platform == "darwin", "macOS editor")
    def test_the_macos_editor_uses_them(self):
        from flippy.mac import pointer_editor
        self.assertIs(pointer_editor.from_hex, pixelart.from_hex)
        self.assertIs(pointer_editor.to_hex, pixelart.to_hex)


class Sliders(unittest.TestCase):
    def test_rgb_moves_in_whole_steps_and_updates_hsb(self):
        rgb, hsv = pixelart.slide("rgb", 0, 0.5, (0, 0, 1), colorsys.rgb_to_hsv(0, 0, 1))
        self.assertEqual(rgb, (128 / 255, 0, 1))
        self.assertEqual(hsv, colorsys.rgb_to_hsv(*rgb))
        self.assertEqual(pixelart.slider_texts("rgb", rgb, hsv), ["128", "0", "255"])

    def test_hsb_keeps_hue_at_black(self):
        rgb, hsv = pixelart.slide("hsb", 2, 0.0, (1, 0, 0), (0.6, 1, 1))  # brightness all the way down
        self.assertEqual(rgb, (0, 0, 0))
        self.assertEqual(hsv, (0.6, 1, 0.0))  # the hue survives, so brightening again gets the same blue back
        rgb, hsv = pixelart.slide("hsb", 2, 1.0, rgb, hsv)
        self.assertEqual(pixelart.to_hex(rgb), pixelart.to_hex(colorsys.hsv_to_rgb(0.6, 1, 1)))
        self.assertEqual(pixelart.slider_texts("hsb", rgb, hsv), ["216°", "100%", "100%"])

    def test_out_of_range_drags_clamp(self):
        rgb, _ = pixelart.slide("rgb", 1, 1.7, (0, 0, 0), (0, 0, 0))
        self.assertEqual(rgb, (0, 1, 0))
        _, hsv = pixelart.slide("hsb", 0, -0.2, (1, 0, 0), (0.3, 1, 1))
        self.assertEqual(hsv[0], 0.0)
        self.assertEqual(pixelart.slider_at("hsb", 1, (1, 0, 0), (0.3, 0.25, 1)), 0.25)
        self.assertEqual(pixelart.slider_at("rgb", 2, (1, 0, 0.5), (0, 1, 1)), 0.5)


if __name__ == "__main__":
    unittest.main()
