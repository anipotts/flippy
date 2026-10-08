"""Video review's frame picking (flippy/video.py), on synthetic thumbnails. Run: python -m unittest discover tests"""
import unittest

from flippy import video

W, H = video.THUMB_W, video.THUMB_H


def frame(shot, t, preview=(24, 8, 72, 40)):
    """A thumbnail: a still editor UI (0.2) with a "video" in the preview box, whose brightness depends on the
    shot (cuts change it a lot) plus some flicker (motion within a shot)."""
    x0, y0, x1, y1 = preview
    px = []
    for y in range(H):
        for x in range(W):
            if x0 <= x < x1 and y0 <= y < y1:
                moving = (x + y) % 2 == 0  # half the preview flickers a little from frame to frame
                px.append(0.15 + 0.3 * (shot % 3) + (0.07 * (t % 2) if moving else 0))
            else:
                px.append(0.2)
    return px


class Picking(unittest.TestCase):
    def setUp(self):
        # 40 frames: shots change at frames 12 and 27
        self.thumbs = [frame(0 if i < 12 else 1 if i < 27 else 2, i) for i in range(40)]

    def test_preview_is_the_part_that_changes(self):
        x0, y0, x1, y1 = video.preview_box(self.thumbs)
        self.assertAlmostEqual(x0, 23 / W, places=2)
        self.assertAlmostEqual(x1, 73 / W, places=2)
        self.assertAlmostEqual(y0, 7 / H, places=2)
        self.assertAlmostEqual(y1, 41 / H, places=2)

    def test_a_still_screen_has_no_preview(self):
        still = [frame(0, 0, preview=(0, 0, 0, 0))] * 10
        self.assertIsNone(video.preview_box(still))

    def test_cuts(self):
        scores = video.step_scores(self.thumbs, video.preview_box(self.thumbs))
        self.assertEqual(sorted(video.find_cuts(scores)), [12, 27])

    def test_no_cuts_in_one_shot(self):
        one = [frame(0, i) for i in range(30)]
        self.assertEqual(video.find_cuts(video.step_scores(one, video.preview_box(one))), [])

    def test_pick_keeps_both_sides_of_each_cut_and_the_ends(self):
        picked = video.pick(40, [12, 27])
        for i in (0, 11, 12, 26, 27, 39):
            self.assertIn(i, picked)
        self.assertLessEqual(len(picked), video.MAX_FRAMES)
        self.assertEqual(picked, sorted(picked))

    def test_pick_short_recording(self):
        self.assertEqual(video.pick(3, []), [0, 1, 2])


class Commands(unittest.TestCase):
    def test_command_parsing(self):
        r = video.Review.__new__(video.Review)
        seen = []
        r.recording = False
        r.start = lambda: seen.append("start") or "ok"
        r.stop = lambda: seen.append("stop") or "ok"
        r.cancel = lambda: seen.append("cancel") or "ok"
        r.ask = lambda q: seen.append(("ask", q)) or "ok"
        for cmd in ("video", "video start", "video stop", "video cancel", "video ask is the cut clean?"):
            r.command(cmd)
        self.assertEqual(seen, ["start", "start", "stop", "cancel", ("ask", "is the cut clean?")])


if __name__ == "__main__":
    unittest.main()
