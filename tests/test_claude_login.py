"""Claude's sign-in runs `claude auth login` in the background, without a terminal (flippy/claude_login.py)."""
import os
import stat
import tempfile
import time
import unittest
from unittest.mock import patch

from flippy import claude_login


class SignIn(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.addCleanup(claude_login.cancel)
        self.log = os.path.join(self.dir.name, "log")
        self.cli = os.path.join(self.dir.name, "claude")
        with open(self.cli, "w") as f:  # stands in for the browser wait
            f.write(f'#!/bin/sh\necho "$* key=${{ANTHROPIC_API_KEY-unset}}" >> "{self.log}"\nsleep 30\n')
        os.chmod(self.cli, os.stat(self.cli).st_mode | stat.S_IXUSR)

    def wait_for(self, check):
        deadline = time.monotonic() + 5
        while not check():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)

    def lines(self):
        try:
            with open(self.log) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def test_subscription_sign_in_without_the_api_key(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            self.assertTrue(claude_login.start(self.cli))
        self.wait_for(self.lines)
        self.assertEqual(self.lines(), ["auth login --claudeai key=unset"])
        self.assertTrue(claude_login.waiting())

    def test_pressing_again_replaces_the_waiting_sign_in(self):
        claude_login.start(self.cli)
        first = claude_login._process
        self.wait_for(self.lines)
        claude_login.start(self.cli)
        self.wait_for(lambda: first.poll() is not None)
        self.assertTrue(claude_login.waiting())
        self.wait_for(lambda: len(self.lines()) == 2)

    def test_gives_up_after_the_timeout(self):
        with patch.object(claude_login, "TIMEOUT", 0.2):
            claude_login.start(self.cli)
        self.wait_for(lambda: not claude_login.waiting())

    def test_missing_cli(self):
        self.assertFalse(claude_login.start(os.path.join(self.dir.name, "nope")))
        self.assertFalse(claude_login.waiting())


if __name__ == "__main__":
    unittest.main()
