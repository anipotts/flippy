"""Every failure shows a short sentence and a documented code (flippy/errors.py, docs/errors.md)."""
import asyncio
import os
import re
import unittest

from flippy import errors
from flippy.brain import BrainError
from flippy.codex_provider import CodexError, CodexSignInRequired
from flippy.providers import ProviderChoiceRequired
from flippy.usage_guard import PlanLimitReached

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Codes(unittest.TestCase):
    def test_claude_reply_errors_by_kind(self):
        for kind, code in (("authentication_failed", "CLAUDE-LOGIN"), ("billing_error", "CLAUDE-BILLING"),
                           ("rate_limit", "CLAUDE-RATE"), ("invalid_request", "CLAUDE-REJECTED"),
                           ("server_error", "CLAUDE-BUSY"), ("unknown", "CLAUDE-FAILED"),
                           ("incomplete", "CLAUDE-INCOMPLETE")):
            self.assertEqual(errors.code_of(BrainError("x", kind=kind)), code)

    def test_claude_sdk_failures(self):
        from claude_agent_sdk import CLIConnectionError, CLINotFoundError, ProcessError
        self.assertEqual(errors.code_of(CLINotFoundError("gone")), "CLAUDE-MISSING")
        self.assertEqual(errors.code_of(CLIConnectionError("no")), "CLAUDE-START")
        self.assertEqual(errors.code_of(ProcessError("boom", exit_code=1)), "CLAUDE-FAILED")

    def test_other_sources(self):
        self.assertEqual(errors.code_of(CodexError("x", "CODEX-OLD")), "CODEX-OLD")
        self.assertEqual(errors.code_of(CodexSignInRequired("x")), "CODEX-LOGIN")
        self.assertEqual(errors.code_of(ProviderChoiceRequired("x", kind="pick")), "PICK-PROVIDER")
        self.assertEqual(errors.code_of(PlanLimitReached("limit")), "PLAN-LIMIT")
        self.assertEqual(errors.code_of(asyncio.TimeoutError()), "TIMEOUT")
        self.assertEqual(errors.code_of(ConnectionResetError()), "NETWORK")
        self.assertEqual(errors.code_of(ValueError("?")), "UNKNOWN")

    def test_shown_text_is_fixed_but_the_log_has_the_detail(self):
        shown, logged = errors.describe(BrainError("Overloaded: secret internals", kind="server_error"))
        self.assertEqual(shown, "Claude is having trouble right now. Try again in a minute. · CLAUDE-BUSY")
        self.assertIn("secret internals", logged)
        self.assertNotIn("secret", shown)
        shown, _ = errors.describe(PlanLimitReached("You've reached your Claude plan's limit. It resets at 3 PM."))
        self.assertTrue(shown.startswith("You've reached your Claude plan's limit. It resets at 3 PM."))

    def test_every_code_is_documented_and_every_codex_raise_has_a_known_code(self):
        doc = open(os.path.join(ROOT, "docs", "errors.md")).read()
        for code in errors.CODES:
            self.assertIn(f"## {code}", doc)
        source = open(os.path.join(ROOT, "flippy", "codex_provider.py")).read()
        for code in re.findall(r'CodexError\([^\n]*?, "([A-Z-]+)"\)', source):
            self.assertIn(code, errors.CODES)
        for mapping in (errors.CLAUDE_KINDS, errors.PROVIDER_KINDS, errors.ACT_REASONS):
            self.assertTrue(set(mapping.values()) <= set(errors.CODES))


if __name__ == "__main__":
    unittest.main()
