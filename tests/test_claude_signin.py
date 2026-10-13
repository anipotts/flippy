"""Claude's sign-in runs `claude auth login` in the background (no terminal) and watches `claude auth status`."""
import json
import signal
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flippy import claude_signin
from flippy.claude_signin import ALREADY, RUNNING, STARTED, SignIn
from flippy.providers import CONNECTION_STATUS

CLI = "/opt/sdk/_bundled/claude"


class FakeProcess:
    """A login process that exits (with rc) after `lives` polls, or only when signalled."""

    def __init__(self, lives=None, rc=0):
        self.pid, self.returncode, self.lives, self.rc, self.signals = 4242, None, lives, rc, []

    def poll(self):
        if self.returncode is None and self.lives is not None:
            self.lives -= 1
            if self.lives < 0:
                self.returncode = self.rc
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("claude", timeout)
        return self.returncode

    def send_signal(self, sig):
        self.signals.append(sig)
        self.returncode = -sig


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class TestClaudeSignIn(unittest.TestCase):
    def setUp(self):
        previous = dict(CONNECTION_STATUS)
        self.addCleanup(lambda: CONNECTION_STATUS.update(previous))
        for target, value in (("claude_cli", Mock(return_value=CLI)), ("log", Mock())):
            p = patch.object(claude_signin, target, value)
            p.start()
            self.addCleanup(p.stop)
        killpg = patch.object(claude_signin.os, "killpg", side_effect=self._killpg)
        killpg.start()
        self.addCleanup(killpg.stop)
        self.clock = Clock()
        self.process = FakeProcess()
        self.popen = Mock(return_value=self.process)
        self.answers = []
        self.status = Mock(side_effect=lambda cli, env: self.answers.pop(0) if self.answers else False)

    def _killpg(self, pid, sig):
        self.assertEqual(pid, self.process.pid)
        self.process.send_signal(sig)

    def signin(self):
        return SignIn(popen=self.popen, status=self.status, clock=self.clock, sleep=self.clock.sleep, thread=False)

    def test_starts_the_cli_login_in_the_background_without_an_api_key(self):
        self.answers = [True]
        with patch.dict(claude_signin.os.environ, {"ANTHROPIC_API_KEY": "sk-test", "FLIPPY_BUNDLED": "1",
                                                   "PATH": "/usr/bin"}):
            self.assertEqual(self.signin().start(connected=False), STARTED)
        argv = self.popen.call_args.args[0]
        kwargs = self.popen.call_args.kwargs
        self.assertEqual(argv, [CLI, "auth", "login", "--claudeai"])
        self.assertNotIn("ANTHROPIC_API_KEY", kwargs["env"])
        self.assertNotIn("FLIPPY_BUNDLED", kwargs["env"])
        self.assertEqual(kwargs["env"]["PATH"], "/usr/bin")
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)  # nothing to type into: no terminal
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)  # its sign-in URL is never read or logged
        self.assertTrue(kwargs["start_new_session"])

    def test_already_signed_in_does_not_start_a_new_login(self):
        CONNECTION_STATUS["claude"] = True
        fallback = Mock()
        self.assertEqual(self.signin().start(fallback=fallback), ALREADY)
        self.popen.assert_not_called()
        fallback.assert_not_called()

    def test_reconnect_after_confirming_starts_anyway(self):
        CONNECTION_STATUS["claude"] = True
        self.process.lives = 0
        self.answers = [True]
        self.assertEqual(self.signin().start(force=True), STARTED)
        self.popen.assert_called_once()

    def test_reconnect_waits_for_the_new_login_not_the_old_one(self):
        CONNECTION_STATUS["claude"] = True
        self.process.lives = 2  # the new browser sign-in finishes after two polls
        self.answers = [True]  # what status says once it has exited
        signin = self.signin()
        signin.start(force=True)
        self.assertEqual(signin.result, "signed-in")
        self.assertEqual(self.status.call_count, 1)  # the old login didn't end it early
        self.assertEqual(self.process.signals, [])

    def test_success_via_status_poll_marks_connected_and_stops_the_login(self):
        CONNECTION_STATUS["claude"] = False
        self.answers = [False, False, True]  # the user takes two polls to finish in the browser
        done = Mock()
        signin = self.signin()
        self.assertEqual(signin.start(on_done=done), STARTED)
        done.assert_called_once_with("signed-in")
        self.assertEqual(signin.result, "signed-in")
        self.assertIs(CONNECTION_STATUS["claude"], True)
        self.assertEqual(self.status.call_count, 3)
        self.assertEqual(self.process.signals, [signal.SIGTERM])  # still waiting after the grace: stopped
        self.assertFalse(signin.running())

    def test_login_exiting_after_saving_counts_as_signed_in(self):
        self.process.lives = 1  # exits on its own between polls
        self.answers = [False, False, True]
        signin = self.signin()
        signin.start(connected=False)
        self.assertEqual(signin.result, "signed-in")
        self.assertEqual(self.process.signals, [])

    def test_timeout_kills_the_login(self):
        CONNECTION_STATUS["claude"] = False
        signin = self.signin()
        signin.start(timeout=10)
        self.assertEqual(signin.result, "timeout")
        self.assertEqual(self.process.signals, [signal.SIGTERM])
        self.assertIsNot(CONNECTION_STATUS["claude"], True)
        self.assertGreaterEqual(self.clock.now, 10)

    def test_stubborn_login_gets_sigkill(self):
        self.process.send_signal = lambda sig: self.process.signals.append(sig) or (
            sig == signal.SIGKILL and setattr(self.process, "returncode", -sig))
        signin = self.signin()
        signin.start(connected=False, timeout=4)
        self.assertEqual(self.process.signals, [signal.SIGTERM, signal.SIGKILL])
        self.assertEqual(self.process.returncode, -signal.SIGKILL)

    def test_cancel_stops_a_pending_login(self):
        signin = SignIn(popen=self.popen, status=self.status, clock=self.clock, sleep=self.clock.sleep, thread=False)
        signin.watch = Mock()  # leave it pending, as if the watcher thread were still polling
        signin.start(connected=False)
        self.assertTrue(signin.running())
        signin.cancel()
        self.assertEqual(self.process.signals, [signal.SIGTERM])

    def test_second_click_while_pending_does_not_start_another(self):
        signin = self.signin()
        signin.watch = Mock()
        self.assertEqual(signin.start(connected=False), STARTED)
        self.assertEqual(signin.start(connected=False), RUNNING)
        self.popen.assert_called_once()

    def test_falls_back_to_the_terminal_when_the_cli_cannot_start(self):
        self.popen.side_effect = PermissionError
        fallback = Mock(return_value="terminal")
        self.assertEqual(self.signin().start(connected=False, fallback=fallback), "terminal")
        fallback.assert_called_once_with()
        self.assertIn("couldn't start the claude CLI (PermissionError)", claude_signin.log.call_args.args[0])

    def test_falls_back_when_the_login_fails_right_away(self):
        self.process.lives, self.process.rc = 0, 1
        fallback = Mock()
        signin = self.signin()
        signin.start(connected=False, fallback=fallback)
        self.assertEqual(signin.result, "exited")
        fallback.assert_called_once_with()

    def test_no_cli_falls_back(self):
        claude_signin.claude_cli.return_value = None
        fallback = Mock(return_value="terminal")
        self.assertEqual(self.signin().start(connected=False, fallback=fallback), "terminal")
        self.popen.assert_not_called()


class TestStatus(unittest.TestCase):
    def run_with(self, stdout, rc=0):
        return lambda *a, **k: SimpleNamespace(stdout=stdout, returncode=rc)

    def test_only_a_claude_ai_login_counts(self):
        ok = json.dumps({"loggedIn": True, "authMethod": "claude.ai"})
        self.assertTrue(claude_signin.signed_in(CLI, run=self.run_with(ok)))
        api = json.dumps({"loggedIn": True, "authMethod": "api-key"})
        self.assertFalse(claude_signin.signed_in(CLI, run=self.run_with(api)))
        out = json.dumps({"loggedIn": False, "authMethod": "none"})
        self.assertFalse(claude_signin.signed_in(CLI, run=self.run_with(out, rc=1)))
        self.assertFalse(claude_signin.signed_in(CLI, run=self.run_with(b"not json")))

    def test_hung_or_missing_cli_is_not_signed_in(self):
        def hang(*a, **k):
            raise subprocess.TimeoutExpired("claude", 10)
        self.assertFalse(claude_signin.signed_in(CLI, run=hang))
        self.assertFalse(claude_signin.signed_in(CLI, run=Mock(side_effect=FileNotFoundError)))


if __name__ == "__main__":
    unittest.main()
