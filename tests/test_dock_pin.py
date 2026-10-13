"""Where answers show (flippy/overlay.py: next to the pointer, or a corner) and the card's pushpin (flippy/themes.py)."""
import types
import unittest
from unittest.mock import MagicMock, patch

import cairo

from flippy import daemon, overlay, settings, themes

W, H = 1440, 900
SHORT = "Click Save."
LONG = " ".join(["This answer goes on for a while so it needs a lot of room on the screen."] * 14)


class Overlay(overlay.OverlayBase):
    def queue_draw(self): pass
    def set_opacity(self, a): pass
    def start_ticking(self): pass
    def stop_ticking(self): pass
    def set_drawing_input(self, on): pass


class Base(unittest.TestCase):
    def setUp(self):
        saver = patch.object(settings, "_save")
        saver.start()
        self.addCleanup(saver.stop)
        for key, value in (("theme", "mono"), ("card_place", "auto"), ("controls", "all")):
            old = settings.get("look", key)
            self.addCleanup(settings.set, "look", key, old)
            settings.set("look", key, value)
        self.ov = Overlay()

    def answer(self, text, at=(400, 300)):
        if at:
            self.ov.point(*at, "Save")
        self.ov.show_text(text, header="Save" if at else None, follow=bool(at), controls=True)
        return self.ov.card_layout(W, H)[0]


class Placement(Base):
    def test_a_short_answer_stays_by_the_pointer(self):
        x, y, w, h = self.answer(SHORT)
        self.assertEqual(self.ov.card_mode, "follow")
        self.assertFalse(self.ov.docked)
        self.assertLess(abs(x - 400), 80)

    def test_a_big_answer_goes_to_the_top_right_and_stays_there(self):
        x, y, w, h = self.answer(LONG)
        self.assertTrue(self.ov.docked)
        self.assertEqual((x + w, y), (W - overlay.CORNER_GAP, overlay.OverlayBase.card_margin_top))
        x2, y2, w2, h2 = self.answer(SHORT, at=(600, 500))  # the next step of the walkthrough: no jumping back
        self.assertEqual((x2 + w2, y2), (W - overlay.CORNER_GAP, overlay.OverlayBase.card_margin_top))

    def test_an_answer_with_nothing_to_point_at_goes_to_a_corner(self):
        self.answer(SHORT, at=None)
        self.assertEqual(self.ov.card_mode, "dock")

    def test_an_answer_over_the_text_you_are_working_in_moves(self):
        self.ov.avoid = (0, 0, 900, H)  # an editor on the left of the screen
        x, y, w, h = self.answer(SHORT, at=(300, 300))
        self.assertTrue(self.ov.docked)
        self.assertGreater(x, 900)  # the corner off the editor

    def test_text_elsewhere_doesnt_move_it(self):
        self.ov.avoid = (1000, 600, 300, 200)
        self.answer(SHORT, at=(300, 300))
        self.assertFalse(self.ov.docked)

    def test_the_corner_avoids_the_pointer(self):
        x, y, w, h = self.answer(LONG, at=(W - 60, 120))  # pointing at something under the top-right corner
        self.assertTrue(self.ov.docked)
        self.assertFalse(x <= W - 60 <= x + w and y <= 120 <= y + h)

    def test_the_setting(self):
        settings.set("look", "card_place", "pointer")
        self.answer(LONG)
        self.assertFalse(self.ov.docked)
        self.answer(SHORT, at=None)
        self.assertNotEqual(self.ov.card_mode, "dock")
        self.ov.clear()
        settings.set("look", "card_place", "corner")
        self.answer(SHORT)
        self.assertTrue(self.ov.docked)

    def test_notices_and_thinking_stay_where_they_were(self):
        self.ov.show_text("thinking…", phase="thinking")
        self.assertEqual(self.ov.card_mode, "top")
        self.ov.show_text("Couldn't answer.", error=True)
        self.assertEqual(self.ov.card_mode, "top")

    def test_a_new_answer_starts_over(self):
        self.answer(LONG)
        self.ov.pinned = True
        self.ov.clear()
        self.assertFalse(self.ov.docked or self.ov.pinned)
        self.answer(SHORT)
        self.assertFalse(self.ov.docked)


class Pushpin(Base):
    def paint(self):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        self.ov.paint(cairo.Context(surface), W, H)
        return self.ov.hits

    def test_every_theme_has_one_inside_the_card_and_clear_of_its_controls(self):
        for key in themes.THEMES:
            for text, follow in ((SHORT, True), (LONG, False)):
                with self.subTest(theme=key, long=text is LONG):
                    settings.set("look", "theme", key)
                    self.ov.clear()
                    self.answer(text, at=(400, 300) if follow else None)
                    hits = self.paint()
                    self.assertIn("pin", hits)
                    (x, y, w, h), _ = self.ov.card_layout(W, H)
                    px, py, pw, ph = hits["pin"]
                    self.assertTrue(x <= px and px + pw <= x + w and y <= py and py + ph <= y + h)
                    for name, rect in hits.items():
                        if name != "pin":
                            self.assertEqual(overlay._overlap(hits["pin"], rect), 0, name)

    def test_only_on_answers(self):
        for fields in ({"phase": "thinking"}, {"error": True}, {}):
            self.ov.show_text("x", **fields)
            self.assertNotIn("pin", self.paint())

    def test_drawn_both_ways(self):
        self.answer(SHORT)
        for pinned in (False, True):
            self.ov.card.pinned = pinned
            self.paint()


class PinTiming(unittest.TestCase):
    def fake(self, play=None, pinned=False):
        ov = types.SimpleNamespace(pinned=pinned, card=themes.Card(text="x", controls=True), queue_draw=lambda: None)
        return types.SimpleNamespace(overlay=ov, play=play, _cancel_fade=MagicMock(), _schedule_fade=MagicMock())

    def test_pinning_stops_the_fade(self):
        d = self.fake()
        with patch.object(daemon, "event"):
            daemon.Flippy.toggle_pin(d)
        self.assertTrue(d.overlay.pinned and d.overlay.card.pinned)
        d._cancel_fade.assert_called_once()
        d._schedule_fade.assert_not_called()

    def test_unpinning_a_finished_answer_fades_it(self):
        d = self.fake(play=types.SimpleNamespace(paused=False, finished=True), pinned=True)
        with patch.object(daemon, "event"):
            daemon.Flippy.toggle_pin(d)
        d._schedule_fade.assert_called_once_with(settings.get("timing", "show_seconds"))

    def test_unpinning_while_playing_leaves_the_fade_to_the_end(self):
        d = self.fake(play=types.SimpleNamespace(paused=False, finished=False), pinned=True)
        with patch.object(daemon, "event"):
            daemon.Flippy.toggle_pin(d)
        d._schedule_fade.assert_not_called()

    def test_a_pinned_answer_never_schedules_a_fade(self):
        d = types.SimpleNamespace(overlay=types.SimpleNamespace(pinned=True), _cancel_fade=MagicMock())
        with patch.object(daemon.loop, "timeout_add") as timeout_add:
            daemon.Flippy._schedule_fade(d, 8)
        timeout_add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
