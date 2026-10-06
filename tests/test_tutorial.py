"""Which questions get a click-gated tutorial (flippy.daemon.wants_tutorial)."""
import unittest

from flippy.daemon import wants_tutorial


class TestTutorialIntent(unittest.TestCase):
    def test_how_to_questions_are_tutorials(self):
        for q in ("how do I add a new track?", "How to export this as an mp3", "walk me through adding a drum kit",
                  "teach me to record vocals", "show me how to split a clip", "step by step, set up a sidechain",
                  "where do I click to change the tempo?", "help me set up a new project", "how can I mute this",
                  "now add a bass loop under the drums", "add some keys", "ok, now make it louder",
                  "let's add a drum fill", "can you open the loop browser"):
            self.assertTrue(wants_tutorial(q), q)

    def test_questions_and_advice_are_not(self):
        for q in ("what's a strong opening move for white here?", "what does this knob do?", "what app is this?",
                  "is this error bad?", "which of these plugins is best for vocals?", "show me the clock",
                  "explain what a bitcrusher is", "is it ok to add more reverb?", "what does adding swing do?"):
            self.assertFalse(wants_tutorial(q), q)


if __name__ == "__main__":
    unittest.main()
