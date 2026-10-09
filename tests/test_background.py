"""Background desktop tasks (flippy/actions.py BACKGROUND_CATALOG): controls by number, refusals that let the
task go on, and what approval cards say."""
import asyncio
import sys
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

    async def test_click_scroll_drag_by_position_in_the_screenshot(self):
        self.assertIn("click", self.tools.catalog())
        await self.tools.invoke("look", {})
        await self.tools.invoke("click", {"x": 50, "y": 40, "count": 1, "reason": "play"})
        await self.tools.invoke("scroll", {"x": 50, "y": 40, "direction": "down", "lines": 3, "reason": "more"})
        await self.tools.invoke("drag", {"x": 10, "y": 10, "to_x": 60, "to_y": 60, "reason": "move"})
        self.assertEqual([n for n, _ in self.done], ["click", "scroll", "drag"])
        self.assertFalse(self.tools.cancel.is_set())

    async def test_a_spot_off_the_screenshot_is_a_retry_not_a_stop(self):
        await self.tools.invoke("look", {})
        r = await self.tools.invoke("click", {"x": 500, "y": 40, "count": 1, "reason": "x"})
        self.assertTrue(r["is_error"])
        self.assertIn("outside the screenshot", r["content"][0]["text"])
        self.assertFalse(self.tools.cancel.is_set())
        self.assertEqual(self.done, [])


class NoWindow(unittest.IsolatedAsyncioTestCase):
    async def test_a_look_without_a_window_is_text_only_and_media_works(self):
        done = []

        async def capture():
            return AppFrame(None, (0, 0), TARGET, {}, "App: Spotify — no window open.\nMenus: Playback: Next")

        async def approve(name, args, shot):
            return True

        async def perform(name, args, shot, cancel):
            done.append((name, args))
        tools = DesktopTools(capture, approve, perform, approval_mode="per_app", max_actions=40, max_text=2000,
                             catalog=BACKGROUND_CATALOG, prompt=BACKGROUND_PROMPT)
        r = await tools.invoke("look", {})
        self.assertEqual([c["type"] for c in r["content"]], ["text"])  # no image, still a look
        await tools.invoke("media", {"action": "next", "reason": "skip"})
        await tools.invoke("menu", {"path": ["Playback", "Next"], "reason": "skip"})
        self.assertEqual([n for n, _ in done], ["media", "menu"])
        r = await tools.invoke("media", {"action": "eject", "reason": "x"})
        self.assertTrue(r["is_error"])


@unittest.skipUnless(sys.platform == "darwin", "macOS key codes")
class Keys(unittest.TestCase):
    def test_every_key_offered_to_claude_has_a_key_code(self):
        from flippy.actions import APP_KEYS
        from flippy.mac import ax
        for combo in APP_KEYS:
            name = combo.split("+")[-1]
            self.assertIsNotNone(ax.NAV_KEYS.get(name, ax.hotkeys.KEYS.get(name)), combo)


class Coordinates(unittest.TestCase):
    def test_screenshot_pixels_map_to_the_window_on_screen(self):
        f = AppFrame("x", (200, 100), ("com.apple.textedit", 1, 7, (300, 50, 100, 50), 0), {}, "")
        self.assertEqual(f.to_logical(0, 0), (300, 50))
        self.assertEqual(f.to_logical(100, 50), (350, 75))  # a 2x screenshot: half the points

    def test_no_screenshot_means_no_clicking_by_position(self):
        f = AppFrame(None, (0, 0), TARGET, {}, "")
        with self.assertRaises(RetryableActionError):
            f.to_logical(1, 1)


class Describe(unittest.TestCase):
    def test_cards_say_what_will_happen_in_words(self):
        f = frame()
        self.assertTrue(f.describe("press", {"element": 2, "reason": "r"}).startswith("press 'Save'"))
        self.assertTrue(f.describe("menu", {"path": ["File", "New"], "reason": "r"}).startswith("choose File > New"))
        self.assertIn('"text": "hi"', f.describe("type", {"text": "hi", "reason": "r"}))


if __name__ == "__main__":
    unittest.main()
