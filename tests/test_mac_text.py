"""The answer card's text on macOS (flippy/mac/text.py): characters the theme's font lacks fall back to fonts that
have them, instead of drawing as boxes."""
import sys
import unittest


@unittest.skipUnless(sys.platform == "darwin", "macOS text drawing")
class Fallback(unittest.TestCase):
    def test_symbols_the_theme_font_lacks_use_a_fallback_font(self):
        import cairo
        from flippy.mac import text
        cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10))
        lay = text.Layout(cr, "", "Noto Sans", 16)  # Helvetica Neue on macOS
        for ch in "→✓⌘∗★中😀":
            face = next(f for f, _ in lay._runs(ch))
            self.assertIsNot(face, lay.face, ch)          # not the theme font, which lacks it...
            self.assertTrue(text._has(face, ch, 16), ch)  # ...but one that has it

    def test_plain_text_stays_in_the_theme_font(self):
        import cairo
        from flippy.mac import text
        cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10))
        lay = text.Layout(cr, "", "Noto Sans", 16)
        self.assertEqual([(f, t) for f, t in lay._runs("Click Save, then *wait*.")], [(lay.face, "Click Save, then *wait*.")])

    def test_wrapping_measures_fallback_characters(self):
        import cairo
        from flippy.mac import text
        cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10))
        lay = text.Layout(cr, "✓ ✓ ✓ ✓ ✓ ✓ ✓ ✓ ✓ ✓", "Noto Sans", 16, width=60)
        self.assertGreater(len(lay.lines()), 1)
        self.assertTrue(all(lay._w(ln) <= 60 for ln in lay.lines()))


if __name__ == "__main__":
    unittest.main()
