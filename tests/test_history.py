"""The question box's Up/Down history (flippy/history.py)."""
import unittest

from flippy.history import PromptHistory


class History(unittest.TestCase):
    def test_up_goes_back_and_down_returns_to_the_draft(self):
        h = PromptHistory()
        for p in ("one", "two", "three"):
            h.add(p)
        self.assertEqual(h.older("half typ"), "three")
        self.assertEqual(h.older("three"), "two")
        self.assertEqual(h.older("two"), "one")
        self.assertIsNone(h.older("one"))           # nothing older: stays on the oldest
        self.assertEqual(h.newer("one"), "two")
        self.assertEqual(h.newer("two"), "three")
        self.assertEqual(h.newer("three"), "half typ")  # past the newest: what was being typed
        self.assertIsNone(h.newer("half typ"))

    def test_empty_history_does_nothing(self):
        h = PromptHistory()
        self.assertIsNone(h.older("x"))
        self.assertIsNone(h.newer("x"))

    def test_consecutive_duplicates_and_blanks_are_kept_once(self):
        h = PromptHistory()
        for p in ("a", "a ", "", "   ", "b", "a"):
            h.add(p)
        self.assertEqual(h.items, ["a", "b", "a"])

    def test_sending_or_reopening_starts_from_the_newest(self):
        h = PromptHistory()
        h.add("one")
        h.add("two")
        h.older("")
        h.older("two")
        h.add("three")                               # sent: back to the newest end
        self.assertEqual(h.older(""), "three")
        h.reset()                                    # the box closed and opened again
        self.assertEqual(h.older(""), "three")

    def test_keeps_only_the_last_prompts_and_covers_act(self):
        h = PromptHistory(size=3)
        for p in ("1", "2", "/act open Notes", "4"):
            h.add(p)
        self.assertEqual(h.items, ["2", "/act open Notes", "4"])


if __name__ == "__main__":
    unittest.main()
