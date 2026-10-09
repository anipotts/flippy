"""Never spend Claude extra usage or ChatGPT credits (flippy/usage_guard.py), and Claude requests honoring it."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flippy import usage_guard
from flippy.usage_guard import Guard, PlanLimitReached

NOW = 1_900_000_000


def info(status="allowed", kind="five_hour", used=None, overage=None, resets=NOW + 3600):
    return SimpleNamespace(status=status, rate_limit_type=kind, utilization=used, overage_status=overage,
                           resets_at=resets)


class Claude(unittest.TestCase):
    def setUp(self):
        self.now = [NOW]
        self.g = Guard("claude", clock=lambda: self.now[0])

    def test_plenty_left_allows(self):
        self.assertFalse(self.g.claude(info(used=0.4)))
        self.g.check()

    def test_extra_usage_stops_now_and_until_reset(self):
        self.assertTrue(self.g.claude(info(kind="overage")))
        with self.assertRaises(PlanLimitReached) as raised:
            self.g.check()
        self.assertIn("never uses extra usage", str(raised.exception))
        self.assertIn("resets", str(raised.exception))
        self.now[0] = NOW + 3601
        self.g.check()  # the window reset

    def test_limit_hit_with_overage_available_stops(self):
        self.assertTrue(self.g.claude(info(status="rejected", overage="allowed")))
        self.assertRaises(PlanLimitReached, self.g.check)

    def test_nearly_full_blocks_new_requests_but_lets_this_one_finish(self):
        self.assertFalse(self.g.claude(info(status="allowed_warning", used=0.96)))
        self.assertRaises(PlanLimitReached, self.g.check)

    def test_a_block_without_a_reset_time_doesnt_last_forever(self):
        self.g.claude(info(status="rejected", resets=None))
        self.assertRaises(PlanLimitReached, self.g.check)
        self.now[0] = NOW + usage_guard.UNKNOWN_RESET_S + 1
        self.g.check()


class Codex(unittest.TestCase):
    def setUp(self):
        self.g = Guard("codex", clock=lambda: NOW)

    def read(self, allowed=True, used=10, reached=None):
        return {"ordinaryUsageAllowed": allowed,
                "rateLimits": {"primary": {"usedPercent": used, "resetsAt": NOW + 600},
                               "rateLimitReachedType": reached}}

    def test_included_usage_used_up_refuses(self):
        self.g.codex_read(self.read(allowed=False, used=100))
        with self.assertRaises(PlanLimitReached) as raised:
            self.g.check()
        self.assertIn("never uses ChatGPT credits", str(raised.exception))

    def test_nearly_full_window_refuses(self):
        self.g.codex_read(self.read(used=96))
        self.assertRaises(PlanLimitReached, self.g.check)

    def test_a_clean_read_lifts_an_earlier_block(self):
        self.g.codex_read(self.read(used=96))
        self.g.codex_read(self.read(used=3))  # e.g. after the window reset
        self.g.check()

    def test_mid_request_update_stops_now(self):
        self.assertTrue(self.g.codex({"rateLimitReachedType": "rate_limit_reached",
                                      "primary": {"usedPercent": 100, "resetsAt": NOW + 60}}))
        self.assertRaises(PlanLimitReached, self.g.check)


class ClaudeRequests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        usage_guard.GUARDS["claude"] = Guard("claude")
        self.addCleanup(lambda: usage_guard.GUARDS.__setitem__("claude", Guard("claude")))

    async def test_a_question_is_cut_off_when_claude_reports_extra_usage(self):
        from claude_agent_sdk import RateLimitEvent, RateLimitInfo
        from flippy import brain

        class Client:
            async def query(self, messages):
                pass

            async def receive_response(self):
                yield RateLimitEvent(rate_limit_info=RateLimitInfo(status="allowed", rate_limit_type="overage"),
                                     uuid="u", session_id="s")
                raise AssertionError("the request should have stopped at the overage report")
        b = brain.Brain()
        b.client = Client()
        with self.assertRaises(PlanLimitReached):
            await b._reply([{"type": "text", "text": "q"}], None)
        with self.assertRaises(PlanLimitReached):  # and the next one never goes out
            await b._reply([{"type": "text", "text": "q"}], None)

    async def test_tasks_and_tips_check_before_sending(self):
        from flippy import brain
        usage_guard.GUARDS["claude"].claude(SimpleNamespace(status="rejected", rate_limit_type="five_hour",
                                                            utilization=1.0, overage_status=None, resets_at=None))
        b = brain.Brain()
        with patch.object(brain, "ClaudeSDKClient", side_effect=AssertionError("must not connect")), \
                patch.object(brain, "query", side_effect=AssertionError("must not send")):
            with self.assertRaises(PlanLimitReached):
                await b.write_tips("App", "", 2, [])
            desktop = SimpleNamespace(catalog=lambda: {}, server=lambda: None, max_turns=4, prompt="p")
            with self.assertRaises(PlanLimitReached):
                await b.act("task", desktop)


if __name__ == "__main__":
    unittest.main()
