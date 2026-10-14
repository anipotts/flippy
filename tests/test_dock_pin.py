"""Where answers show (flippy/overlay.py, flippy/placement.py: by the pointer, or docked out of the way) and the card's pushpin (flippy/themes.py)."""
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

import cairo

from flippy import daemon, overlay, placement, playback, point, settings, themes
from flippy.frames import prepare_frame

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
    def learn(self, keep=None):
        self.ov.learning, self.ov.keep = True, keep

    def test_a_quick_question_stays_by_the_pointer(self):
        x, y, w, h = self.answer(LONG)
        self.assertEqual(self.ov.card_mode, "follow")
        self.assertLess(abs(x - 400), 80)

    def test_learning_docks_away_from_what_they_need_to_see(self):
        code = (0, 0, 1000, H)  # Claude's box: the code on the left
        self.learn(code)
        x, y, w, h = self.answer(SHORT, at=(300, 300))
        self.assertEqual(self.ov.card_mode, "dock")
        self.assertEqual(placement.overlap((x, y, w, h), code), 0)

    def test_and_away_from_the_text_you_are_working_in(self):
        self.ov.avoid = (W - 700, 0, 700, H)  # the editor on the right
        self.learn()
        x, y, w, h = self.answer(SHORT)
        self.assertEqual(placement.overlap((x, y, w, h), self.ov.avoid), 0)

    def test_it_prefers_an_empty_part_of_the_screen(self):
        busy = [1.0] * (8 * 5)
        for c in range(8):
            busy[4 * 8 + c] = 0.0  # only the bottom row of the screen is empty
        self.ov.detail = placement.Detail(busy, 8, 5, (W, H))
        self.learn()
        x, y, w, h = self.answer(SHORT)
        self.assertGreater(y + h, H * 0.75)

    def test_a_docked_card_ignores_the_pointer(self):
        self.learn((0, 0, 700, H))
        first = self.answer(SHORT, at=(300, 300))
        spot = self.ov.spot
        for at in ((W - 60, 120), (60, 120), (W - 60, H - 150)):  # wherever the walkthrough points next, under it too
            self.assertEqual(self.answer(SHORT, at=at), first)
        self.assertEqual(self.ov.spot, spot)

    def test_the_pointer_is_drawn_over_the_card(self):
        self.learn()
        self.answer(LONG, at=(W - 60, 120))
        calls = []
        theme = self.ov.theme
        with patch.object(type(theme), "draw", lambda *a: calls.append("card")), \
                patch.object(overlay.themes, "draw_pointer", lambda *a, **k: calls.append("pointer")):
            self.ov.paint(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)), W, H)
        self.assertEqual(calls, ["card", "pointer"])

    def test_the_setting(self):
        settings.set("look", "card_place", "pointer")
        self.learn()
        self.answer(SHORT)
        self.assertEqual(self.ov.card_mode, "follow")
        self.ov.clear()
        settings.set("look", "card_place", "corner")
        self.answer(SHORT)  # not learning: docked anyway
        self.assertEqual(self.ov.card_mode, "dock")

    def test_notices_and_thinking_stay_where_they_were(self):
        self.learn()
        self.ov.show_text("thinking…", phase="thinking")
        self.assertEqual(self.ov.card_mode, "top")
        self.ov.show_text("Couldn't answer.", error=True)
        self.assertEqual(self.ov.card_mode, "top")

    def test_a_new_answer_starts_over(self):
        self.learn((0, 0, 100, 100))
        self.answer(SHORT)
        self.ov.pinned = True
        self.ov.avoid = self.ov.window = self.ov.detail = (0, 0, 10, 10)
        self.ov.clear()
        self.assertFalse(self.ov.learning or self.ov.pinned or self.ov.keep or self.ov.spot)
        self.assertIsNone(self.ov.avoid or self.ov.window or self.ov.detail)  # a video answer doesn't reuse them

    def test_a_notice_after_a_pinned_answer_fades(self):
        self.answer(SHORT)
        self.ov.pinned = True
        self.ov.show_text("Flippy is acting")  # no pushpin on it, so nothing could unpin it
        self.assertFalse(self.ov.pinned or self.ov.card.pinned)


class LearnTag(unittest.TestCase):
    def test_parsed_and_hidden(self):
        raw = "[LEARN:10,20,300,400] Rust starts in main [POINT:5,5:fn main]."
        found, rest = point.split_learn(raw, True)
        self.assertEqual(found.box, (10, 20, 300, 400))
        self.assertEqual([s.text for s in point.segments(raw, True)], ["Rust starts in main."])

    def test_without_a_box(self):
        self.assertIsNone(point.split_learn("[LEARN] hi", True)[0].box)

    def test_nothing_shows_while_it_streams_in(self):
        for partial in ("[", "[LEA", "[LEARN:10,20,3"):
            self.assertEqual(point.segments(partial, False), [])

    def test_other_replies(self):
        self.assertIsNone(point.split_learn("Click [POINT:1,2:Save].", True)[0])
        self.assertIsNone(point.split_learn("[LEARNING is fun]", True)[0])

    def test_playback(self):
        pl = playback.Playback(0)
        pl.append("[LEARN:1,2,3,4] main")
        self.assertEqual(pl.learn().box, (1, 2, 3, 4))

    def test_a_reply_of_only_tags_shows_no_tag(self):
        pl = playback.Playback(0)
        pl.finish("[LEARN:1,2,3,4][POINT:none]")
        empty = [text for kind, text in pl.tick(1, playback.Options(), lambda x, y: (x, y)) if kind == "empty"]
        self.assertNotIn("LEARN", empty[0])


class Spot(unittest.TestCase):
    def test_never_on_what_to_keep_when_theres_room(self):
        keep = (200, 100, 800, 600)
        x, y = placement.best_spot(W, H, 360, 180, keep=keep)
        self.assertEqual(placement.overlap((x, y, 360, 180), keep), 0)

    def test_near_an_edge_on_an_empty_screen(self):
        x, y = placement.best_spot(W, H, 360, 180)
        self.assertEqual(min(x, W - 360 - x, y, H - 180 - y), placement.GAP)

    def test_a_card_nearly_as_big_as_the_room(self):
        for w, h, cw, ch in ((1440, 900, 480, 749.5), (632.5, 900, 600, 180)):  # fractional sizes, as macOS gives
            x, y = placement.best_spot(w, h, cw, ch, top=40, bottom=110)
            self.assertTrue(0 <= x <= w - cw)

    def test_detail_from_a_screenshot(self):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (640, 400), "white")
        draw = ImageDraw.Draw(img)
        for i in range(0, 200, 8):
            draw.text((10, i), "fn main() { println!(x); }" * 2, fill="black")  # text on the top half
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "screen.png")
            img.save(path)
            frame = prepare_frame(path, 640, logical_size=(W, H))  # the frame an ask really makes
        detail = placement.Detail.from_frame(frame)
        self.assertGreater(detail.mean((0, 0, W / 2, H / 3)), detail.mean((0, H * 0.7, W, H * 0.3)))


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
                            self.assertEqual(placement.overlap(hits["pin"], rect), 0, name)

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


@unittest.skipUnless(sys.platform == "darwin", "macOS Accessibility")
class WorkArea(unittest.TestCase):
    def note(self, found, now):
        f = types.SimpleNamespace(ui=types.SimpleNamespace(work_area=lambda: now), overlay=types.SimpleNamespace())
        daemon.Flippy._note_focus(f, None, found)
        return f.overlay.avoid

    def test_from_the_box_else_read_now(self):
        self.assertEqual(self.note(((1, 1, 5, 5), None), ((9, 9, 5, 5), None)), (1, 1, 5, 5))
        self.assertEqual(self.note(None, ((9, 9, 5, 5), None)), (9, 9, 5, 5))  # flippy-ask q, or the box was closed


class FocusedArea(unittest.TestCase):
    """flippy/mac/ax.py focused_area: what counts as the text you're working in."""
    def area(self, tree, focused):
        from flippy.mac import ax
        attrs = {"root": {"AXFocusedUIElement": focused}, **tree}
        with patch.object(ax, "trusted", return_value=True), patch.object(ax, "_working_app", return_value="root"), \
                patch.object(ax, "_attr", side_effect=lambda el, name: attrs.get(el, {}).get(name)), \
                patch.object(ax, "_frame", side_effect=lambda el: attrs.get(el, {}).get("frame")):
            return ax.focused_area()

    def test_vs_code_cursor_field_means_the_editor_around_it(self):
        tree = {"cursor": {"AXRole": "AXTextArea", "frame": (669, 252, 217, 18), "AXParent": "pane"},
                "pane": {"AXRole": "AXGroup", "frame": (603, 252, 745, 429), "AXWindow": "win"},
                "win": {"frame": (307, 161, 1046, 690)}}
        self.assertEqual(self.area(tree, "cursor"), (603, 252, 745, 429))

    def test_a_terminal_is_clipped_to_its_window(self):
        tree = {"text": {"AXRole": "AXTextArea", "frame": (162, -70, 818, 829), "AXWindow": "win"},
                "win": {"frame": (162, 184, 818, 575)}}
        self.assertEqual(self.area(tree, "text"), (162, 184, 818, 575))

    def test_a_search_field_stays_small(self):
        tree = {"field": {"AXRole": "AXTextField", "frame": (859, 440, 78, 20), "AXParent": "bar"},
                "bar": {"AXRole": "AXGroup", "frame": (0, 400, 1512, 100)}}
        self.assertEqual(self.area(tree, "field"), (859, 440, 78, 20))

    def test_not_text(self):
        self.assertIsNone(self.area({"list": {"AXRole": "AXOutline", "frame": (0, 0, 500, 500)}}, "list"))


if __name__ == "__main__":
    unittest.main()
