"""Help mode's rules (flippy/watch.py), driven with simulated samples. Run: python -m unittest discover tests"""
import unittest

from flippy import watch
from flippy.watch import Sample, Watcher

APP = "com.ableton.live"
A, B, C, D = ([v] * 40 for v in (0.1, 0.4, 0.7, 0.95))  # four clearly different "screens"


class Sim:
    """Feeds a Watcher one sample every SAMPLE_S, tracking time, input count and idle time like a real Mac."""

    def __init__(self, w=None, app=APP):
        self.w = w or Watcher(apps={APP})
        self.t, self.events, self.last_input = 0.0, 0, 0.0
        self.app, self.thumb, self.windows = app, A, [(1, (0, 0, 1200, 800))]
        self.offers = []

    def step(self, inputs=0, thumb=None, windows=None):
        self.t += watch.SAMPLE_S
        if inputs:
            self.events += inputs
            self.last_input = self.t
        if thumb is not None:
            self.thumb = thumb
        if windows is not None:
            self.windows = windows
        offer = self.w.feed(Sample(self.t, self.app, "Ableton Live", self.t - self.last_input, self.events,
                                   self.thumb, self.windows))
        if offer:
            self.offers.append((self.t, offer.reason))
        return offer

    def run(self, seconds, **kw):
        for _ in range(int(seconds / watch.SAMPLE_S)):
            self.step(**kw)


class TestStalled(unittest.TestCase):
    def test_busy_then_still_asks_once(self):
        sim = Sim()
        sim.run(40, inputs=3)          # busy
        sim.run(60)                    # then nothing, screen unchanged
        self.assertEqual([r for _, r in sim.offers], ["stalled"])
        t, _ = sim.offers[0]
        self.assertGreaterEqual(t - 40, watch.STALL_S)

    def test_never_busy_never_asks(self):
        sim = Sim()
        sim.run(120)
        self.assertEqual(sim.offers, [])

    def test_screen_still_moving_is_not_stuck(self):
        sim = Sim()
        sim.run(40, inputs=3)
        for i in range(30):            # no input, but playback keeps changing the screen
            sim.step(thumb=(A, B)[i % 2] if i % 3 == 0 else None)
        self.assertNotIn("stalled", [r for _, r in sim.offers])

    def test_walked_away_does_not_ask(self):
        w = Watcher(apps={APP})
        sim = Sim(w)
        sim.run(40, inputs=3)
        w.last_offer_t = 1e9           # pretend we're in a cooldown the whole time it would have fired...
        sim.run(watch.AWAY_S + 20)
        w.last_offer_t = -1e9          # ...then it ends after they've clearly left
        sim.run(10)
        self.assertEqual(sim.offers, [])

    def test_one_offer_per_stall(self):
        sim = Sim()
        sim.run(40, inputs=3)
        sim.run(170)                   # a long stall, past the cooldown
        self.assertEqual(len(sim.offers), 1)


class TestCircles(unittest.TestCase):
    def test_flipping_between_two_screens_while_clicking(self):
        sim = Sim()
        sim.run(10, inputs=2)
        for i in range(10):
            sim.step(inputs=2, thumb=(B, A)[i % 2])
        self.assertIn("circles", [r for _, r in sim.offers])

    def test_new_screens_each_time_is_progress(self):
        sim = Sim()
        screens = [[v / 20] * 40 for v in range(20)]  # every change is somewhere new
        for th in screens:
            sim.step(inputs=2, thumb=th)
        self.assertEqual(sim.offers, [])


class TestDialog(unittest.TestCase):
    def test_small_centered_window_pops_up(self):
        sim = Sim()
        sim.run(10, inputs=1)
        main = (1, (0, 0, 1200, 800))
        sim.step(windows=[main, (2, (450, 300, 300, 200))])
        self.assertEqual([r for _, r in sim.offers], ["dialog"])

    def test_big_or_offcenter_windows_are_not_dialogs(self):
        sim = Sim()
        main = (1, (0, 0, 1200, 800))
        sim.run(10, inputs=1)
        sim.step(windows=[main, (2, (0, 0, 1100, 760))])        # a second big window
        sim.step(windows=[main, (2, (0, 0, 1100, 760)), (3, (1000, 700, 180, 90))])  # corner popover
        self.assertEqual(sim.offers, [])


class TestPacing(unittest.TestCase):
    def test_only_watched_apps(self):
        sim = Sim(app="com.apple.Safari")
        sim.run(40, inputs=3)
        sim.run(60)
        self.assertEqual(sim.offers, [])

    def test_muted_app(self):
        w = Watcher(apps={APP})
        w.mute(APP)
        sim = Sim(w)
        sim.run(40, inputs=3)
        sim.run(60)
        self.assertEqual(sim.offers, [])

    def test_cooldown_between_offers(self):
        sim = Sim()
        sim.run(10, inputs=1)
        main = (1, (0, 0, 1200, 800))
        sim.step(windows=[main, (2, (450, 300, 300, 200))])
        sim.step(windows=[main, (2, (450, 300, 300, 200)), (3, (460, 310, 280, 180))])
        self.assertEqual(len(sim.offers), 1)

    def test_not_now_backs_off(self):
        w = Watcher(apps={APP})
        w.not_now(APP)
        w.not_now(APP)                 # 2.25x
        sim = Sim(w)
        sim.run(40, inputs=3)
        sim.run(54)
        self.assertEqual(sim.offers, [])  # 25 s x 2.25 = 56 s: not yet
        sim.run(6)
        self.assertEqual([r for _, r in sim.offers], ["stalled"])
        w.helped(APP)
        self.assertAlmostEqual(w.state(APP).backoff, 1.5)

    def test_switching_apps_starts_fresh(self):
        w = Watcher(apps={APP, "org.lmms"})
        sim = Sim(w)
        sim.run(40, inputs=3)
        sim.app = "org.lmms"           # switch right as they go still
        sim.run(60)
        self.assertEqual(sim.offers, [])  # no busy history in LMMS yet


if __name__ == "__main__":
    unittest.main()
