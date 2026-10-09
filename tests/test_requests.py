"""A request's identity and owned resources survive delayed callbacks safely."""
from concurrent.futures import Future
import unittest

from flippy.requests import Request


class TestRequests(unittest.TestCase):
    def test_identity_not_generation_number_controls_ownership(self):
        old = Request(1, "tutor")
        same_number = Request(1, "tutor")
        self.assertTrue(old.owns(old))
        self.assertFalse(old.owns(same_number))
        self.assertFalse(old.owns(None))
        old.cancel(lambda _: None)
        self.assertFalse(old.owns(old))
        self.assertTrue(same_number.owns(same_number))

    def test_cancel_removes_timers_and_cancels_pending_future_once(self):
        request = Request(2, "action", future=Future())
        request.timers.update({3, 4})
        removed = []
        self.assertTrue(request.cancel(removed.append))
        self.assertTrue(request.canceled.is_set())
        self.assertTrue(request.future.cancelled())
        self.assertCountEqual(removed, [3, 4])
        self.assertEqual(request.timers, set())
        self.assertFalse(request.cancel(removed.append))
        self.assertEqual(len(removed), 2)

    def test_cancel_completed_playback_still_removes_owned_timers(self):
        future = Future()
        future.set_result("completed")
        request = Request(3, "video", future=future, pending=False)
        request.timers.add(5)
        removed = []
        request.cancel(removed.append)
        self.assertEqual(removed, [5])
        self.assertEqual(future.result(), "completed")


if __name__ == "__main__":
    unittest.main()
