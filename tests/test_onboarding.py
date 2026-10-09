"""The first-run tour (flippy/onboarding.py): driven by the UI events, start to finish, with a fake controller."""
import unittest
from unittest import mock

from flippy import onboarding, settings


class FakeNudge:
    def __init__(self):
        self.cards = []

    def card(self, head, detail, buttons, **_):
        assert buttons, "cards need at least one button (macOS Nudge.card)"
        self.cards.append((head, detail, buttons))

    def hide(self):
        pass

    @property
    def head(self):
        return self.cards[-1][0]


class FakeUI:
    def __init__(self):
        self.nudge = FakeNudge()

    def key_label(self, name):
        return {"ask": "⇧⌘Space", "draw": "⌃⇧Space", "video": "⌃⌥V", "pause": "double-tap ⌘"}[name]

    def setup_pending(self):
        return False


class FakeFlippy:
    def __init__(self):
        self.ui = FakeUI()
        self.overlay = mock.Mock(hits={"prev": 1, "toggle": 1, "next": 1, "speed_cycle": 1})
        self.box = mock.Mock(visible=True)
        self.settings_opened = False

    def dismiss(self):
        pass

    def open_settings(self):
        self.settings_opened = True


class TestTour(unittest.TestCase):
    def setUp(self):
        self.saved = settings.get("onboarding", "done")
        patcher = mock.patch.object(settings, "_save")  # atomic setter's persistence boundary
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: settings.set("onboarding", "done", self.saved))
        settings.set("onboarding", "done", False)
        self.f = FakeFlippy()
        self.tour = onboarding.Tour(self.f)
        self.timers = mock.patch.object(onboarding.loop, "timeout_add", lambda ms, fn: fn())
        self.timers.start()
        self.addCleanup(self.timers.stop)
        self.events = mock.patch.object(onboarding, "_event", lambda *a, **k: None)
        self.events.start()
        self.addCleanup(self.events.stop)

    def ev(self, name, **data):
        self.tour.on_event(name, data)

    def press(self, title):
        buttons = dict(self.f.ui.nudge.cards[-1][2])
        buttons[title]()

    def test_whole_tour(self):
        self.assertFalse(self.tour.maybe_start())
        self.assertEqual(self.tour.step, "welcome")
        self.press("Let's go")
        self.assertIn("⇧⌘Space", self.f.ui.nudge.head)

        self.ev("box")  # they pressed it: the suggestion gets filled in
        self.f.box.set_text.assert_called_with(onboarding.SUGGEST["ask"])
        self.assertEqual(self.f.ui.nudge.head, "Press Return")
        self.ev("ask", question="...")
        self.assertEqual(self.tour.step, "pause")

        self.ev("point")
        self.assertIn("double-tap ⌘", self.f.ui.nudge.head)
        self.ev("control", control="pause")
        self.assertEqual(self.f.ui.nudge.head, "Paused")
        self.ev("control", control="play")
        self.ev("answer_done")
        self.assertEqual(self.tour.step, "followup")

        self.ev("box")
        self.f.box.set_text.assert_called_with(onboarding.SUGGEST["followup"])
        self.ev("ask")
        self.assertEqual(self.tour.step, "skip")
        self.ev("point")
        self.assertEqual(self.f.ui.nudge.head, "Skip ahead")
        self.ev("control", control="next")
        self.assertEqual(self.f.ui.nudge.head, "Speed me up")
        self.ev("control", control="speed_cycle")
        self.ev("answer_done")
        self.assertEqual(self.tour.step, "follow")

        self.ev("box")
        self.f.box.set_text.assert_called_with(onboarding.SUGGEST["follow"])
        self.ev("ask")
        self.ev("waiting")
        self.assertEqual(self.f.ui.nudge.head, "Your turn")
        self.ev("user_click")
        self.ev("ask")          # the walkthrough's next screenful
        self.ev("answer_done")
        self.assertEqual(self.tour.step, "draw")

        self.ev("draw_start")
        self.ev("draw_cancel")  # let go too early: try again
        self.assertEqual(self.tour.sub, "start")
        self.ev("draw_start")
        self.ev("drawn")
        self.ev("box")
        self.f.box.set_text.assert_called_with(onboarding.SUGGEST["draw"])
        self.ev("ask")
        self.ev("answer_done")
        self.assertEqual(self.tour.step, "video")

        self.press("Next")  # no editor open
        self.assertEqual(self.tour.step, "settings")
        self.assertTrue(self.f.settings_opened)
        self.press("Done")
        self.assertFalse(self.tour.running)
        self.assertTrue(settings.get("onboarding", "done"))
        self.assertFalse(self.tour.maybe_start())  # once is enough
        self.assertFalse(self.tour.running)

    def test_not_now_counts_as_seen(self):
        self.tour.maybe_start()
        self.press("Not now")
        self.assertFalse(self.tour.running)
        self.assertTrue(settings.get("onboarding", "done"))

    def test_waits_for_setup(self):
        self.f.ui.setup_pending = lambda: True
        self.assertTrue(self.tour.maybe_start())  # keep checking
        self.assertFalse(self.tour.running)

    def test_skip_and_end_on_every_waiting_card(self):
        self.tour.start()
        self.press("Let's go")
        for _ in range(6):
            self.assertEqual([t for t, _ in self.f.ui.nudge.cards[-1][2]], ["End tour", "Skip"])
            self.press("Skip")
        self.assertEqual(self.tour.step, "video")

    def test_theme_without_skip_button_goes_to_speed(self):
        self.f.overlay.hits = {"toggle": 1, "speed_cycle": 1}
        self.tour._go("skip")
        self.ev("point")
        self.assertEqual(self.f.ui.nudge.head, "Speed me up")

    def test_video_step_waits_for_a_recording(self):
        self.tour._go("video")
        self.ev("video_start")
        self.ev("video_ask")
        self.ev("answer_done")
        self.assertEqual(self.tour.step, "settings")


if __name__ == "__main__":
    unittest.main()
