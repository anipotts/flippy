"""Tips mode's deck and dealer (flippy/tips.py). Run: python -m unittest discover tests"""
import tempfile
import unittest
from unittest import mock

from flippy import tips, watch
from flippy.brain import BrainError, parse_tips
from flippy.watch import Sample

APP = "com.ableton.live"


def deck(levels):
    d = tips.Deck(APP, "Ableton Live")
    d.add([{"text": f"tip {i} (L{lv})", "level": lv} for i, lv in enumerate(levels)])
    return d


class TestDeck(unittest.TestCase):
    def test_easiest_first(self):
        d = deck([3, 1, 2, 1])
        self.assertEqual(d.next_tip()["level"], 1)

    def test_knew_that_twice_moves_up_a_level(self):
        d = deck([1, 1, 1, 2, 2, 3])
        d.mark(d.next_tip(), "knew")
        self.assertEqual(d.skill, 1)
        d.mark(d.next_tip(), "knew")
        self.assertEqual(d.skill, 2)
        self.assertEqual(d.next_tip()["level"], 2)  # the last level-1 tip is skipped

    def test_got_it_does_not_change_level(self):
        d = deck([1, 1, 2])
        for _ in range(2):
            d.mark(d.next_tip(), "shown")
        self.assertEqual(d.skill, 1)

    def test_falls_back_to_easier_when_nothing_left_at_level(self):
        d = deck([1, 1])
        d.skill = 3
        self.assertIsNotNone(d.next_tip())

    def test_refill_when_low_at_their_level(self):
        d = deck([1] * 10 + [2] * 3)
        self.assertFalse(d.needs_refill())
        d.skill = 2
        self.assertTrue(d.needs_refill())

    def test_no_duplicates_on_refill(self):
        d = deck([1, 2])
        d.add([{"text": "tip 0 (L1)", "level": 1}, {"text": "brand new", "level": 2}])
        self.assertEqual(len(d.tips), 3)

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(tips, "DIR", tmp):
            d = deck([1, 2])
            d.goal = "make a drum loop"
            d.mark(d.tips[0], "shown")
            d.save()
            again = tips.Deck.load(APP)
            self.assertEqual((again.goal, again.tips[0]["state"], len(again.tips)), ("make a drum loop", "shown", 2))
            self.assertIsNone(tips.Deck.load("com.example.missing"))


class TestDealer(unittest.TestCase):
    def run_sim(self, dealer, seconds, inputs_per_sample, pause_every=0, app=APP, t0=0.0, events0=0):
        """Working (inputs each sample), with an optional short pause every `pause_every` seconds."""
        t, events, last_input, hits = t0, events0, t0, []
        step = watch.SAMPLE_S
        while t < t0 + seconds:
            t += step
            pausing = pause_every and (t % pause_every) < 8
            if not pausing:
                events += inputs_per_sample
                last_input = t
            if dealer.feed(Sample(t, app, "Ableton Live", t - last_input, events), {APP}, set()):
                hits.append(t)
                dealer.shown(t)
        return hits

    def test_waits_for_warmup_then_a_calm_moment(self):
        hits = self.run_sim(tips.Dealer(), 200, 2, pause_every=40)
        self.assertTrue(hits)
        self.assertGreaterEqual(hits[0], tips.WARMUP_S)

    def test_spacing_between_tips(self):
        hits = self.run_sim(tips.Dealer(), 1200, 2, pause_every=40)
        self.assertGreaterEqual(len(hits), 2)
        self.assertTrue(all(b - a >= tips.EVERY_S for a, b in zip(hits, hits[1:])))

    def test_never_mid_flow(self):
        self.assertEqual(self.run_sim(tips.Dealer(), 600, 2), [])  # never pauses: never interrupted

    def test_not_when_idle(self):
        self.assertEqual(self.run_sim(tips.Dealer(), 600, 0, pause_every=40), [])

    def test_only_watched_apps(self):
        self.assertEqual(self.run_sim(tips.Dealer(), 600, 2, pause_every=40, app="com.apple.Safari"), [])


class TestParse(unittest.TestCase):
    def test_reply_with_fences_and_chatter(self):
        got = parse_tips('Here you go:\n```json\n[{"text": "Press Tab", "level": 1}, {"text": " ", "level": 1},'
                         ' {"text": "Use groups", "level": 7}]\n```')
        self.assertEqual(got, [{"text": "Press Tab", "level": 1}, {"text": "Use groups", "level": 2}])

    def test_garbage(self):
        with self.assertRaises(BrainError):
            parse_tips("sorry, no")


if __name__ == "__main__":
    unittest.main()
