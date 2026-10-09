"""What worked in each app is remembered (flippy/act_memory.py) and handed to the next task, by tool name only."""
import os
import tempfile
import unittest
from unittest.mock import patch

from flippy import act_memory
from flippy.actions import BACKGROUND_CATALOG, BACKGROUND_PROMPT, DesktopTools, RetryableActionError
from tests.test_background import frame

SPOTIFY = "com.spotify.client"


class Memory(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = patch.object(act_memory, "PATH", os.path.join(d.name, "act_memory.json"))
        p.start()
        self.addCleanup(p.stop)

    def test_nothing_known_adds_nothing_to_the_prompt(self):
        self.assertEqual(act_memory.brief(), "")

    def test_a_finished_task_leaves_its_route_and_note(self):
        act_memory.record([(SPOTIFY, "app_action spotify.open_search", True), (SPOTIFY, "click", True),
                           (SPOTIFY, "click (real pointer)", True)],
                          {SPOTIFY: "play a song: open_search, then click the Top result with real_pointer true"},
                          {SPOTIFY: "Spotify"}, finished=True)
        brief = act_memory.brief()
        self.assertIn("Spotify (com.spotify.client)", brief)
        self.assertIn("app_action spotify.open_search -> click -> click (real pointer)", brief)
        self.assertIn("how: play a song", brief)

    def test_a_stopped_task_keeps_the_old_route_but_counts_misses(self):
        act_memory.record([(SPOTIFY, "app_action spotify.play_uri", True)], {}, {}, finished=True)
        act_memory.record([(SPOTIFY, "press", False), (SPOTIFY, "press", False), (SPOTIFY, "click", True)], {}, {},
                          finished=False)
        brief = act_memory.brief()
        self.assertIn("last time that finished: app_action spotify.play_uri", brief)
        self.assertIn("often not done here: press (x2)", brief)

    def test_a_broken_file_is_ignored(self):
        with open(act_memory.PATH, "w") as f:
            f.write("{nope")
        self.assertEqual(act_memory.brief(), "")
        act_memory.record([(SPOTIFY, "click", True)], {}, {}, finished=True)
        self.assertIn("click", act_memory.brief())

    def test_steps_are_tool_names_never_their_text(self):
        self.assertEqual(act_memory.step_name("type", {"text": "secret", "reason": "r"}), "type")
        self.assertEqual(act_memory.step_name("app_action", {"action": "notes.new_note", "args": {"body": "secret"}}),
                         "app_action notes.new_note")
        self.assertEqual(act_memory.step_name("click", {"x": 1, "y": 2, "real_pointer": True}), "click (real pointer)")


class Journal(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fail_with = None

        async def capture():
            return frame()

        async def approve(name, args, shot):
            return True

        async def perform(name, args, shot, cancel):
            if self.fail_with:
                raise self.fail_with
        self.tools = DesktopTools(capture, approve, perform, approval_mode="auto", max_actions=40, max_text=2000,
                                  catalog=BACKGROUND_CATALOG, prompt=BACKGROUND_PROMPT)

    async def test_steps_and_refusals_are_journaled_per_app(self):
        await self.tools.invoke("look", {})
        await self.tools.invoke("press", {"element": 2, "reason": "save"})
        self.fail_with = RetryableActionError("greyed out")
        await self.tools.invoke("menu", {"path": ["File", "Save"], "reason": "save"})
        self.assertEqual(self.tools.journal, [("com.apple.textedit", "press", True),
                                              ("com.apple.textedit", "menu", False)])

    async def test_a_bad_request_isnt_blamed_on_the_tool(self):
        await self.tools.invoke("look", {})
        await self.tools.invoke("press", {"element": 99, "reason": "x"})  # no such control: the model's mistake
        self.assertEqual(self.tools.journal, [])

    async def test_remember_saves_a_note_for_the_app_in_view(self):
        r = await self.tools.invoke("remember", {"how": "x"})
        self.assertTrue(r["is_error"])  # nothing looked at yet
        await self.tools.invoke("look", {})
        r = await self.tools.invoke("remember", {"how": "save: menu File > Save;  press is ignored"})
        self.assertNotIn("is_error", r)
        self.assertEqual(self.tools.notes, {"com.apple.textedit": "save: menu File > Save; press is ignored"})
        self.assertEqual(self.tools.actions, 0)  # not an input
        r = await self.tools.invoke("remember", {"how": "x" * 301})
        self.assertTrue(r["is_error"])


if __name__ == "__main__":
    unittest.main()
