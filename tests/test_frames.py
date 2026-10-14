"""Decoded-pixel freshness and model/native coordinate mapping."""
import base64
import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from flippy.frames import ScreenFrame, prepare_frame


class TestFrames(unittest.TestCase):
    def test_scaled_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "screen.png")
            Image.new("RGB", (80, 40), "blue").save(path)
            frame = prepare_frame(path, 40, logical_size=(40, 20))
            self.assertEqual((frame.original_size, frame.size, frame.logical_size), ((80, 40), (40, 20), (40, 20)))
            with Image.open(io.BytesIO(base64.b64decode(frame.jpeg))) as prepared:
                self.assertEqual(prepared.format, "JPEG")
                self.assertEqual(prepared.size, frame.size)

    def test_full_resolution_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "screen.png")
            Image.new("RGBA", (60, 30), (255, 0, 0, 255)).save(path)
            frame = prepare_frame(path, 0)
            self.assertEqual(frame.size, (60, 30))
            self.assertEqual(frame.content()[1]["data"], frame.jpeg)
            self.assertIn("60x30", frame.content()[0]["text"])

    def test_retina_mapping_and_strict_action_bounds(self):
        frame = ScreenFrame("", (1920, 1080), (1440, 810))
        self.assertEqual(frame.to_logical(960, 540), (720, 405))
        self.assertEqual(frame.to_logical(0, 0), (0, 0))
        for point in ((-1, 0), (0, -1), (1920, 0), (0, 1080), (float("nan"), 0), (float("inf"), 0)):
            with self.assertRaises(ValueError):
                frame.to_logical(*point)
        self.assertEqual(frame.to_logical(-10, 2000, clamp=True), (0, 1079 * 810 / 1080))


if __name__ == "__main__":
    unittest.main()
