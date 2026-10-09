"""The Draw editor's hex color field (flippy/mac/pointer_editor.py)."""
import sys
import unittest


@unittest.skipUnless(sys.platform == "darwin", "macOS editor")
class Hex(unittest.TestCase):
    def setUp(self):
        from flippy.mac import pointer_editor
        self.pe = pointer_editor

    def test_round_trip_and_short_forms(self):
        self.assertEqual(self.pe.to_hex((0.25, 0.6, 1.0)), "#4099FF")
        self.assertEqual(self.pe.from_hex("#4099ff"), (64 / 255, 153 / 255, 1.0))
        self.assertEqual(self.pe.from_hex("fff"), (1.0, 1.0, 1.0))

    def test_junk_is_refused(self):
        for text in ("", "#12345", "zzzzzz", "#1234567"):
            self.assertIsNone(self.pe.from_hex(text))


if __name__ == "__main__":
    unittest.main()
