"""The acting card (#21): the step, Claude's reason, what Claude last said, and how to stop."""
import types
import unittest
from unittest.mock import MagicMock, patch

import cairo

from flippy import daemon, overlay, settings, themes
from flippy.actions import AppFrame


def flippy():
    return types.SimpleNamespace(act_status={"step": None, "reason": None, "thought": None, "trail": []},
                                 _owns=lambda req: True,
                                 _stop_hint=lambda: "⌘ ⌘", overlay=MagicMock())


def card(f):
    args, kwargs = f.overlay.show_text.call_args
    return kwargs["header"], args[0], kwargs["thought"]


class ActingCard(unittest.TestCase):
    def test_before_the_first_step(self):
        f = flippy()
        daemon.Flippy._acting(f, "req")
        self.assertEqual(card(f), (None, "Flippy is acting · ⌘ ⌘ to stop", None))

    def test_step_reason_then_thought(self):
        f = flippy()
        daemon.Flippy._acting(f, "req", "press 'Search'", "to find the jazz playlist")
        self.assertEqual(card(f), ("Press 'Search'", "to find the jazz playlist\n⌘ ⌘ to stop", None))
        daemon.Flippy._acting(f, "req", thought="Spotify is open; looking for search first.")
        self.assertEqual(card(f), ("Press 'Search'", "to find the jazz playlist\n⌘ ⌘ to stop",
                                   "Spotify is open; looking for search first."))  # in the card's thinking section
        daemon.Flippy._acting(f, "req", "switch to Music", "play it there")  # a new step keeps the last thought
        self.assertEqual(card(f)[0], "Switch to Music")
        self.assertIn("looking for search first", card(f)[2])

    def test_the_trail_for_the_result_card(self):
        f = flippy()
        for thought in ("Opening Spotify.", "Opening Spotify.", "Searching for jazz.", "Playing Kind of Blue."):
            daemon.Flippy._acting(f, "req", thought=thought)
        self.assertEqual(f.act_status["trail"], ["Opening Spotify.", "Searching for jazz.", "Playing Kind of Blue."])
        # Claude's last message is the result itself: the strip under it holds what came before
        self.assertEqual(daemon.Flippy._act_trail(f, "Playing Kind of Blue."), "Opening Spotify.\n\nSearching for jazz.")
        self.assertIsNone(daemon.Flippy._act_trail(types.SimpleNamespace()))  # no task ran
        f.act_status["trail"] = [f"Thought {i}. " + "x" * 200 for i in range(6)]
        kept = daemon.Flippy._act_trail(f)
        self.assertLessEqual(len(kept), daemon.TRAIL_CHARS)
        self.assertTrue(kept.endswith(f.act_status["trail"][-1]))  # the latest ones

    def test_a_stopped_task_carries_it(self):
        overlay = MagicMock()
        daemon.Flippy._fail(types.SimpleNamespace(busy=True, _stop_playback=MagicMock(), overlay=overlay,
                                                  _schedule_fade=MagicMock()), "Desktop task stopped.", thought="why")
        self.assertEqual(overlay.show_text.call_args.kwargs["thought"], "why")

    def test_a_finished_request_leaves_the_card_alone(self):
        f = flippy()
        f._owns = lambda req: False
        daemon.Flippy._acting(f, "req", "press 'Save'", "save it")
        f.overlay.show_text.assert_not_called()

    def test_long_thoughts_show_their_end(self):
        self.assertEqual(daemon._last_words("First part.\n\nThen this."), "Then this.")
        long = daemon._last_words("x" * 500 + " the end.")
        self.assertEqual(len(long), daemon.THOUGHT_CHARS)
        self.assertTrue(long.startswith("…") and long.endswith("the end."))

    def test_steps_in_words(self):
        frame = AppFrame("", (0, 0), ("app", 1, 2, (0, 0, 10, 10)), {3: (None, None, "Search")}, "")
        self.assertEqual(frame.describe("press", {"element": 3, "reason": "find it"}).split("\n")[0], "press 'Search'")


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
