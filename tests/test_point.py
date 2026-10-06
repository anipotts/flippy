"""POINT tags (flippy/point.py), including Flippy's ":click" flag for gated tutorial steps."""
import unittest

from flippy.point import parse_reply, segments


class TestTags(unittest.TestCase):
    def test_plain_tag(self):
        _, pt = parse_reply("Click Wi-Fi [POINT:10,20:Wi-Fi]")
        self.assertEqual((pt.x, pt.y, pt.label, pt.action), (10, 20, "Wi-Fi", False))

    def test_click_flag(self):
        _, pt = parse_reply("Click Wi-Fi [POINT:10,20:Wi-Fi:click]")
        self.assertEqual((pt.label, pt.action), ("Wi-Fi", True))

    def test_click_flag_with_screen(self):
        _, pt = parse_reply("Open it [POINT:5,6:File menu:click:screen2]")
        self.assertEqual((pt.label, pt.action), ("File menu", True))

    def test_none(self):
        text, pt = parse_reply("Just an answer. [POINT:none]")
        self.assertEqual((text, pt), ("Just an answer.", None))

    def test_segments_carry_the_flag(self):
        segs = segments("This is the tempo [POINT:1,2:Tempo]. Now click Track [POINT:3,4:Track:click].", True)
        self.assertEqual([(s.point.label, s.point.action) for s in segs], [("Tempo", False), ("Track", True)])
        self.assertEqual(segs[1].text, "Now click Track.")

    def test_streaming_half_a_flagged_tag_is_hidden(self):
        segs = segments("Click it [POINT:3,4:Track:cl", False)
        self.assertEqual(segs[-1].text, "Click it")


if __name__ == "__main__":
    unittest.main()
