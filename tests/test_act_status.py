"""A desktop task's card (#21): no player controls, and what Claude said in a thinking section inside it."""
import types
import unittest
from unittest.mock import MagicMock, patch

import cairo

from flippy import daemon, overlay, settings, themes


class Overlay(overlay.OverlayBase):
    def queue_draw(self): pass
    def set_opacity(self, a): pass
    def start_ticking(self): pass
    def stop_ticking(self): pass
    def set_drawing_input(self, on): pass


real_layout = themes.layout
THOUGHT = "Spotify is open. The search box is in the sidebar, so I'll press it and type the genre."


class ThinkingSection(unittest.TestCase):
    """A desktop task's card in every theme: no player controls, and what Claude said at the bottom of the card."""
    WINDOW = {"thought", "close", "min", "max"}  # the Media Player keeps its window buttons

    def setUp(self):
        saver = patch.object(settings, "_save")
        saver.start()
        self.addCleanup(saver.stop)
        old = settings.get("look", "theme")
        self.addCleanup(settings.set, "look", "theme", old)
        settings.set("look", "theme", "mono")
        self.ov = Overlay()

    def paint(self, W=1000, H=700):
        self.ov.paint(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)), W, H)
        return self.ov.hits

    def test_every_theme_open_and_folded(self):
        for key in themes.THEMES:
            settings.set("look", "theme", key)
            for header in ("Press 'Search'", None):  # acting, then the result
                heights = []
                for open_ in (True, False):
                    with self.subTest(theme=key, header=header, open=open_):
                        self.ov.thought_open = open_
                        self.ov.show_text("to find the jazz playlist", header=header, thought=THOUGHT, task=True)
                        (x, y, w, h), _ = self.ov.card_layout(1000, 700)
                        hits = self.paint()
                        self.assertLessEqual(set(hits), self.WINDOW)  # no prev/next/seek/speed
                        tx, ty, tw, th = hits["thought"]
                        self.assertTrue(x <= tx and y < ty and ty + th <= y + h + 0.5)  # inside the card
                        heights.append(h)
                self.assertGreater(heights[0], heights[1])  # folded is one line

    def test_no_flippy_title_on_a_task(self):
        settings.set("look", "theme", "glass")
        self.ov.show_text("Playing Kind of Blue.", thought=THOUGHT, task=True)
        self.assertIsNone(self.ov.theme._title(self.ov.card))
        drawn = []
        def layout(cr, text, *args, **kwargs):
            drawn.append(text)
            return real_layout(cr, text, *args, **kwargs)
        with patch.object(themes, "layout", layout):
            settings.set("look", "theme", "mediaplayer")
            self.paint()
        self.assertNotIn("Flippy", drawn)

    def test_walkthroughs_keep_the_player(self):
        for key in ("glass", "mediaplayer"):
            settings.set("look", "theme", key)
            with self.subTest(theme=key):
                self.ov.show_text("A walkthrough answer.", controls=True)
                self.assertTrue({"prev", "next"} <= set(self.paint()))

    def test_no_section_without_a_thought(self):
        self.ov.show_text("Done.", task=True)
        self.assertNotIn("thought", self.paint())

    def test_clicking_it_folds_and_opens_it(self):
        f = types.SimpleNamespace(overlay=self.ov, dismiss=MagicMock(), toggle_pin=MagicMock(), busy=True)
        with patch.object(daemon, "event"):
            daemon.Flippy.control(f, "thought")
            self.assertFalse(self.ov.thought_open)
            daemon.Flippy.control(f, "thought")
        self.assertTrue(self.ov.thought_open)

    def test_opening_it_on_a_finished_card_gives_time_to_read(self):
        self.ov.show_text("Done.", thought=THOUGHT, task=True)
        f = types.SimpleNamespace(overlay=self.ov, busy=False, _schedule_fade=MagicMock())
        with patch.object(daemon, "event"):
            daemon.Flippy.control(f, "thought")
        f._schedule_fade.assert_called_once()


if __name__ == "__main__":
    unittest.main()
