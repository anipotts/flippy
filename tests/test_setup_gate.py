"""Setup opens by itself only on install, a new major version, or a lost login (flippy/setup_gate.py)."""
import os
import tempfile
import unittest
from unittest.mock import patch

from flippy import setup_gate
from flippy.providers import ProviderChoiceRequired

CONNECTED = {"claude": True, "codex": None}


class Gate(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for target, attr, value in ((setup_gate, "PATH", os.path.join(d.name, "setup.json")),
                                    (setup_gate, "_USED_BEFORE", False)):
            p = patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        self.version = patch.object(setup_gate.updates, "current_version", return_value="0.3.0")
        self.version.start()
        self.addCleanup(self.version.stop)

    def test_a_new_install_opens_it_once(self):
        self.assertEqual(setup_gate.launch_reason(CONNECTED, "auto"), "install")
        setup_gate.mark_seen()
        self.assertIsNone(setup_gate.launch_reason(CONNECTED, "auto"))

    def test_an_existing_user_isnt_shown_it_by_an_update(self):
        with patch.object(setup_gate, "_USED_BEFORE", True):
            self.assertIsNone(setup_gate.launch_reason(CONNECTED, "auto"))

    def test_minor_and_patch_updates_dont_open_it_but_a_major_does(self):
        setup_gate.mark_seen()
        with patch.object(setup_gate.updates, "current_version", return_value="0.9.4"):
            self.assertIsNone(setup_gate.launch_reason(CONNECTED, "auto"))
        with patch.object(setup_gate.updates, "current_version", return_value="1.0.0"):
            self.assertEqual(setup_gate.launch_reason(CONNECTED, "auto"), "major")

    def test_a_lost_login_opens_it_but_an_unchecked_one_doesnt(self):
        setup_gate.mark_seen()
        self.assertEqual(setup_gate.launch_reason({"claude": False, "codex": True}, "claude"), "relogin")
        self.assertIsNone(setup_gate.launch_reason({"claude": None, "codex": None}, "claude"))
        self.assertEqual(setup_gate.launch_reason({"claude": False, "codex": False}, "auto"), "relogin")
        self.assertIsNone(setup_gate.launch_reason({"claude": True, "codex": True}, "auto"))  # a pick, not a login

    def test_requests_failing_on_login(self):
        lost = {"claude": False, "codex": None}
        self.assertTrue(setup_gate.login_error(ProviderChoiceRequired("Connect"), lost, "claude"))
        self.assertFalse(setup_gate.login_error(ProviderChoiceRequired("Both"), {"claude": True, "codex": True}, "auto"))
        self.assertTrue(setup_gate.login_error(RuntimeError("401 authentication_error"), CONNECTED, "claude"))
        self.assertFalse(setup_gate.login_error(TimeoutError(), CONNECTED, "claude"))


if __name__ == "__main__":
    unittest.main()
