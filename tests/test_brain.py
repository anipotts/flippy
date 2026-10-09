"""Claude sessions (flippy/brain.py): nothing Flippy asks, screenshots included, is saved to disk."""
import asyncio
import unittest
from unittest import mock

from flippy import brain


class TestNoTranscripts(unittest.TestCase):
    def test_main_session_is_not_saved(self):
        self.assertIn("no-session-persistence", brain.Brain().options.extra_args)

    def test_tips_session_is_not_saved(self):
        seen = {}

        async def fake_query(prompt, options):
            seen["extra_args"] = options.extra_args
            return
            yield  # an async generator that yields nothing
        with mock.patch.object(brain, "query", fake_query):
            with self.assertRaises(brain.BrainError):  # an empty reply has no tips; only the options matter
                asyncio.run(brain.Brain().write_tips("TextEdit", "", 2, []))
        self.assertIn("no-session-persistence", seen["extra_args"])


if __name__ == "__main__":
    unittest.main()
