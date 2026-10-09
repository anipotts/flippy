"""Scripted app actions for /act (flippy/mac/scripts.py): a fixed list, and the user's text never becomes script."""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flippy.actions import BACKGROUND_CATALOG, BACKGROUND_PROMPT, RetryableActionError


@unittest.skipUnless(sys.platform == "darwin", "AppleScript")
class Scripts(unittest.TestCase):
    def run_action(self, action, args, stdout="ok"):
        from flippy.mac import scripts
        with patch.object(scripts.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=stdout, stderr="")) as run:
            out = scripts.run(action, args)
        return out, run.call_args

    def test_text_goes_as_arguments_never_into_the_script(self):
        evil = '" & (do shell script "rm -rf ~") & "'
        out, call = self.run_action("notes.new_note", {"title": evil, "body": "hi"})
        argv, script = call.args[0], call.kwargs["input"]
        self.assertEqual(argv[:2], ["/usr/bin/osascript", "-"])
        self.assertEqual(argv[2], evil)                 # passed as data...
        self.assertNotIn("rm -rf", script)              # ...never in the script source
        self.assertIn("&lt;", self.run_action("notes.new_note", {"title": "t", "body": "<b>x</b>"})[1].args[0][3])

    def test_only_listed_actions(self):
        from flippy.mac import scripts
        with self.assertRaises(RetryableActionError):
            scripts.run("do_shell_script", {"cmd": "ls"})

    def test_checks_values(self):
        from flippy.mac import scripts
        with self.assertRaises(RetryableActionError):
            scripts.run("spotify.play_uri", {"uri": "https://example.com"})
        with self.assertRaises(RetryableActionError):
            scripts.run("safari.open_url", {"url": "file:///etc/passwd"})
        with self.assertRaises(RetryableActionError):
            scripts.run("notes.new_note", {"title": "only a title"})

    def test_mail_never_sends(self):
        from flippy.mac import scripts
        script = scripts.ACTIONS["mail.new_draft"][2]
        self.assertNotIn("send", script.replace("sent", ""))


class Tool(unittest.TestCase):
    def test_app_action_is_offered_and_the_prompt_ranks_the_pointer_last(self):
        self.assertIn("app_action", BACKGROUND_CATALOG)
        order = [BACKGROUND_PROMPT.index(s) for s in ("1. The app's controls", "2. app_action", "3. click",
                                                       "4. Last resort")]
        self.assertEqual(order, sorted(order))


if __name__ == "__main__":
    unittest.main()


class ResultReachesTheModel(unittest.IsolatedAsyncioTestCase):
    async def test_a_scripted_result_comes_back_with_the_next_look(self):
        from flippy.actions import AppFrame, DesktopTools
        frame = AppFrame("x", (10, 10), ("com.spotify.client", 1, 1, (0, 0, 10, 10), 0), {}, "App: Spotify")

        async def capture():
            return frame

        async def approve(*a):
            return True

        async def perform(name, args, shot, cancel):
            return "No L's — Smino (playing)"
        tools = DesktopTools(capture, approve, perform, approval_mode="auto", max_actions=5, max_text=500,
                             catalog=BACKGROUND_CATALOG, prompt=BACKGROUND_PROMPT)
        await tools.invoke("look", {})
        r = await tools.invoke("app_action", {"action": "spotify.now_playing", "args": {}, "reason": "check"})
        self.assertEqual(r["content"][0]["text"], "app_action result: No L's — Smino (playing)")
        self.assertIn("App: Spotify", r["content"][1]["text"])
