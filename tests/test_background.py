"""Background desktop tasks (flippy/actions.py BACKGROUND_CATALOG): controls by number, refusals that let the
task go on, and what approval cards say."""
import asyncio
import threading
import unittest

from flippy.actions import (BACKGROUND_CATALOG, BACKGROUND_PROMPT, AppFrame, DesktopTools, RetryableActionError)

TARGET = ("com.apple.textedit", 4242, 7, (0, 0, 100, 100), 0)


def frame(n=2):
    elements = {1: (object(), "AXTextArea", "body", [], True), 2: (object(), "AXButton", "Save", ["AXPress"], False)}
    return AppFrame("anBn", (100, 100), TARGET, dict(list(elements.items())[:n]), "App: TextEdit\n[1] text area\n[2] button")


class Background(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.done = []
        self.approved = []
        self.fail_with = None

        async def capture():
            return frame()

        async def approve(name, args, shot):
            self.approved.append(name)
            return True

        async def perform(name, args, shot, cancel):
            if self.fail_with:
                raise self.fail_with
            self.done.append((name, args))
        self.tools = DesktopTools(capture, approve, perform, approval_mode="per_app", max_actions=40, max_text=2000,
                                  catalog=BACKGROUND_CATALOG, prompt=BACKGROUND_PROMPT)

    async def test_look_then_act_on_controls_by_number(self):
        r = await self.tools.invoke("look", {})
        self.assertIn("App: TextEdit", r["content"][0]["text"])
        r = await self.tools.invoke("press", {"element": 2, "reason": "save"})
        self.assertNotIn("is_error", r)
        r = await self.tools.invoke("set_text", {"element": 1, "text": "hello", "reason": "write"})
        self.assertNotIn("is_error", r)
        await self.tools.invoke("menu", {"path": ["File", "New"], "reason": "new doc"})
        self.assertEqual([n for n, _ in self.done], ["press", "set_text", "menu"])
        self.assertEqual(self.tools.actions, 3)

    async def test_unknown_control_number_is_a_retry_not_a_stop(self):
        await self.tools.invoke("look", {})
        r = await self.tools.invoke("press", {"element": 99, "reason": "x"})
        self.assertTrue(r["is_error"])
        self.assertIn("Not done", r["content"][0]["text"])
        self.assertIn("App: TextEdit", r["content"][1]["text"])  # a fresh look comes with it
        self.assertFalse(self.tools.cancel.is_set())
        self.assertEqual(self.done, [])

    async def test_app_refusal_is_a_retry_not_a_stop(self):
        await self.tools.invoke("look", {})
        self.fail_with = RetryableActionError("Format > Bold is greyed out right now.")
        r = await self.tools.invoke("menu", {"path": ["Format", "Bold"], "reason": "bold"})
        self.assertIn("greyed out", r["content"][0]["text"])
        self.assertFalse(self.tools.cancel.is_set())
        self.fail_with = None
        r = await self.tools.invoke("press", {"element": 2, "reason": "save"})
        self.assertNotIn("is_error", r)

    async def test_old_coordinate_tools_are_not_offered(self):
        self.assertNotIn("click", self.tools.catalog())
        await self.tools.invoke("look", {})
        r = await self.tools.invoke("click", {"x": 1, "y": 1, "reason": "x"})
        self.assertTrue(r["is_error"])
        self.assertTrue(self.tools.cancel.is_set())  # not a tool here at all: invalid, so it stops


class Describe(unittest.TestCase):
    def test_cards_say_what_will_happen_in_words(self):
        f = frame()
        self.assertTrue(f.describe("press", {"element": 2, "reason": "r"}).startswith("press 'Save'"))
        self.assertTrue(f.describe("menu", {"path": ["File", "New"], "reason": "r"}).startswith("choose File > New"))
        self.assertIn('"text": "hi"', f.describe("type", {"text": "hi", "reason": "r"}))


if __name__ == "__main__":
    unittest.main()
