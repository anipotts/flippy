"""A follow-up question in the middle of a walkthrough, answered on the side, then back to the step (#26)."""
import types
import unittest
from unittest.mock import MagicMock, patch

from flippy import daemon, settings
from flippy.playback import Options, Playback
from flippy.requests import Request

WALKTHROUGH = "Open File [POINT:10,20:File] then Export [POINT:30,40:Export:click] done."


def at(point):
    return (point.x, point.y)


class Parking(unittest.TestCase):
    def test_parked_step_stops_waiting_and_is_pointed_again(self):
        p = Playback(0)
        p.finish(WALKTHROUGH)
        o = Options(tutorial=True, clicks_available=True)
        p.step, p.shown = 1, 99
        events = p.tick(1, o, at)
        self.assertIn(("watch_clicks", True), events)
        self.assertEqual(p.park(), [("watch_clicks", False)])
        self.assertTrue(p.paused)
        self.assertFalse(p.waiting)
        p.resume(5)
        self.assertFalse(p.paused)
        events = p.tick(5.1, o, at)
        self.assertEqual(events[0][0], "point")  # the pointer goes back to the step
        self.assertIn(("watch_clicks", True), events)  # and it waits for its click again
        self.assertEqual(p.step, 1)

    def test_parked_while_waiting_for_more_it_holds_the_step_showing(self):
        p = Playback(0)
        p.append("Open File [POINT:10,20:File] then")
        o = Options()
        p.tick(0.1, o, at)
        p.tick(1, o, at)
        p.tick(9, o, at)  # its hold is over: on to a step not in yet
        self.assertEqual(p.step, 1)
        p.park()
        self.assertEqual(p.step, 0)
        self.assertEqual(p.card(10, o)["step"], 0)

    def test_resume_after_the_end_plays_the_step_again(self):
        p = Playback(0)
        p.finish("Only this [POINT:1,2:x]")
        o = Options()
        p.tick(1, o, at)
        p.tick(9, o, at)
        self.assertTrue(p.finished)
        p.park()
        p.resume(10)
        self.assertFalse(p.finished)
        self.assertEqual(p.tick(10.1, o, at)[0][0], "point")


def flippy():
    """The real controller methods, on a stand-in with no native UI."""
    f = daemon.Flippy.__new__(daemon.Flippy)
    f.gen, f.busy, f.quitting, f.tutorial = 5, False, False, True
    f.request = None
    f.action_tools = None
    f.marked = f.input_disabled = False
    f.play_id = f.fade_id = f.fade_animation_id = 0
    f.followup_token = f.focus_at_open = None
    f.act_hold = None
    f.overlay = MagicMock(drawing=False, card=None)
    f.box = types.SimpleNamespace(visible=False, show=MagicMock(), hide=MagicMock())
    f.ui = types.SimpleNamespace(screen_size=lambda: (1000, 800), scale=lambda: 1.0)
    f.video = types.SimpleNamespace(recording=False)
    pl = Playback(0)
    pl.gen, pl.img, pl.shot, pl.frame, pl.asked = 5, (1000, 800), (1000, 800), None, True
    pl.append(WALKTHROUGH)
    f.play = pl
    return f


class Queue:
    def __init__(self):
        self.calls = []

    def timeout_add(self, ms, fn):
        self.calls.append(fn)
        return len(self.calls)

    idle_add = lambda self, fn: self.timeout_add(0, fn)

    def source_remove(self, timer):
        pass

    def run(self):
        calls, self.calls = self.calls, []
        for fn in calls:
            if fn():
                self.calls.append(fn)


class FollowUp(unittest.TestCase):
    def setUp(self):
        self.queue = Queue()
        for p in (patch.object(daemon, "loop", self.queue), patch.object(daemon, "event"),
                  patch.object(settings, "_save")):
            p.start()
            self.addCleanup(p.stop)

    def follow_up(self, f):
        f.play.tick(0.1, f._play_options(), f._play_coords)
        f.play.shown = 99
        daemon.Flippy.open_box(f)  # the ask hotkey, with a walkthrough on screen
        return f.parked

    def test_the_hotkey_sets_the_walkthrough_aside_and_esc_goes_back(self):
        f = flippy()
        pl = self.follow_up(f)
        self.assertIsNotNone(pl)
        self.assertIsNone(f.play)
        self.assertTrue(pl.paused)
        f.box.show.assert_called_once()
        self.assertTrue(f.overlay.show_text.call_args.kwargs["paused"])  # its card stays up, paused
        f.box.visible = True
        f._box_cancel()  # Esc in the question box
        self.assertIs(f.play, pl)
        self.assertIsNone(f.parked)
        self.assertFalse(pl.paused)
        self.assertTrue(f.tutorial)
        f.box.hide.assert_called()

    def test_the_question_carries_the_step_and_is_answered_on_the_side(self):
        f = flippy()
        self.follow_up(f)
        f._run_request, f._ask = MagicMock(), MagicMock()
        f._begin_request = lambda mode: Request(6, mode)
        f.submit("where is that menu?")
        question = f._ask.call_args.args[0]
        self.assertTrue(question.startswith('[A follow-up in the middle of your walkthrough, at step 1 of 2 so far: '
                                            '"Open File" (you\'re pointing at File).'))
        self.assertIn("where is that menu?", question)
        self.assertIn("not a tutorial", question)
        self.assertFalse(f.tutorial)
        self.assertIsNotNone(f.parked)  # kept until they go back or drop it
        self.assertEqual(f._resume_action(), {"actions": (("resume", "Back to step 1"),)})

    def test_a_walkthrough_still_streaming_finishes_before_the_follow_up_is_asked(self):
        f = flippy()
        req = f.request = Request(5, "tutor")
        f.busy = True
        pl = self.follow_up(f)
        req.cancel = MagicMock()
        f.submit("why?")
        req.cancel.assert_not_called()  # the rest of the walkthrough keeps coming
        f._stream_text(5, " More.")
        self.assertTrue(pl.raw.endswith("More."))
        f._ask, f._run_request = MagicMock(), MagicMock()
        f._begin_request = lambda mode: Request(6, mode)
        self.queue.run()
        f._ask.assert_not_called()  # still waiting
        req.drained.set()
        f.busy = False
        self.queue.run()
        self.assertIn("why?", f._ask.call_args.args[0])

    def test_back_to_the_step_drops_a_side_answer_still_coming(self):
        f = flippy()
        pl = self.follow_up(f)
        side = f.request = Request(6, "tutor")
        f.busy = True
        f.control("resume")
        self.assertTrue(side.canceled.is_set())
        self.assertIs(f.play, pl)

    def test_dismiss_or_a_command_drops_it(self):
        f = flippy()
        self.follow_up(f)
        with patch.object(daemon.Flippy, "open_settings"):
            f.submit("/settings")
        self.assertIsNone(f.parked)
        f = flippy()
        self.follow_up(f)
        with patch.object(daemon.Flippy, "cancel_draw"):
            f.dismiss()
        self.assertIsNone(f.parked)

    def test_a_mark_drawn_for_the_follow_up_goes_with_esc(self):
        f = flippy()
        self.follow_up(f)
        f.marked = True
        f.box.visible = True
        f._box_cancel()
        self.assertFalse(f.marked)
        f.overlay.clear.assert_called()

    def test_cancelling_a_drawing_goes_back_to_the_walkthrough(self):
        f = flippy()
        pl = self.follow_up(f)
        f._end_draw_mode = MagicMock()
        f.cancel_draw()
        self.assertIs(f.play, pl)
        self.assertIsNone(f.parked)

    def test_its_own_controls_go_back_to_it(self):
        f = flippy()
        pl = self.follow_up(f)
        f.control("next")
        self.assertIs(f.play, pl)
        self.assertEqual(pl.step, 1)

    def test_a_one_step_answer_is_not_a_walkthrough(self):
        f = flippy()
        f.play = Playback(0)
        f.play.gen, f.play.frame, f.play.img, f.play.shot, f.play.asked = 5, None, (1000, 800), (1000, 800), True
        f.play.finish("It's in the File menu [POINT:10,20:File]")
        f.play.tick(0.1, f._play_options(), f._play_coords)
        f._render_step(f.play, 0.2)
        self.assertNotIn("actions", f.overlay.show_text.call_args.kwargs)
        daemon.Flippy.open_box(f)
        self.assertIsNone(f.parked)  # the hotkey asks as before
        f = flippy()
        f.play.asked = False  # a video review's or a demo's
        self.assertFalse(f._walkthrough_up())

    def test_a_walkthrough_card_offers_a_follow_up(self):
        f = flippy()
        f.play.tick(0.1, f._play_options(), f._play_coords)
        f._render_step(f.play, 0.2)
        self.assertEqual(f.overlay.show_text.call_args.kwargs["actions"], (("followup", "Follow up"),))


if __name__ == "__main__":
    unittest.main()
