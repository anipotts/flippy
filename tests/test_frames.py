"""Decoded-pixel freshness and model/native coordinate mapping."""
import base64
import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from flippy.frames import ScreenFrame, prepare_frame, prepare_image


class TestFrames(unittest.TestCase):
    def test_fingerprint_ignores_png_metadata_but_detects_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b, c = [Path(directory, name + ".png") for name in "abc"]
            image = Image.new("RGB", (80, 40), "blue")
            image.save(a)
            metadata = PngInfo()
            metadata.add_text("comment", "different encoding, same screen")
            image.save(b, pnginfo=metadata, compress_level=0)
            image.putpixel((79, 39), (255, 0, 0))
            image.save(c)
            fa, fb, fc = [prepare_frame(path, 40, logical_size=(40, 20), target=("window",))
                          for path in (a, b, c)]
            self.assertEqual(fa.fingerprint, fb.fingerprint)
            self.assertNotEqual(fa.fingerprint, fc.fingerprint)
            self.assertEqual(fa.original_size, (80, 40))
            self.assertEqual(fa.size, (40, 20))
            self.assertEqual(fa.logical_size, (40, 20))
            self.assertEqual(fa.target, ("window",))
            with Image.open(io.BytesIO(base64.b64decode(fa.jpeg))) as prepared:
                self.assertEqual(prepared.format, "JPEG")
                self.assertEqual(prepared.size, fa.size)

    def test_fingerprint_includes_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            frames = []
            for size in ((8, 4), (4, 8)):
                path = Path(directory, str(size) + ".png")
                Image.new("RGB", size, "black").save(path)
                frames.append(prepare_frame(path))
            self.assertNotEqual(frames[0].fingerprint, frames[1].fingerprint)

    def test_full_resolution_and_compatibility_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "screen.png")
            Image.new("RGBA", (60, 30), (255, 0, 0, 255)).save(path)
            frame = prepare_frame(path, 0)
            self.assertEqual(frame.size, (60, 30))
            self.assertEqual(prepare_image(path, 0), (frame.jpeg, frame.size, frame.original_size))
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
