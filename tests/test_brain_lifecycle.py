"""SDK protocol fakes prove transport lifetime without authentication or inference."""
import asyncio
import copy
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent, TextBlock

from flippy.brain import Brain, BrainError


def success(text="finished"):
    return [AssistantMessage([TextBlock(text)], "fixture-model"),
            ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                          is_error=False, num_turns=1, session_id="fixture")]


class Client:
    def __init__(self, options, events, *, blocked=False, cleanup_blocked=False):
        self.options = copy.copy(options)
        self.events = events
        self.query_started = asyncio.Event()
        self.release_response = asyncio.Event()
        self.disconnect_started = asyncio.Event()
        self.release_disconnect = asyncio.Event()
        if not blocked:
            self.release_response.set()
        if not cleanup_blocked:
            self.release_disconnect.set()
        self.connected = False
        self.disconnected = False
        self.queries = []

    async def connect(self):
        self.connected = True

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *_args):
        await self.disconnect()

    async def query(self, messages):
        self.queries.append(messages if isinstance(messages, str) else [message async for message in messages])
        self.query_started.set()

    async def receive_response(self):
        if self.events and isinstance(self.events[0], StreamEvent):
            yield self.events[0]
            remaining = self.events[1:]
        else:
            remaining = self.events
        await self.release_response.wait()
        for event in remaining:
            yield event

    async def disconnect(self):
        self.disconnect_started.set()
        await self.release_disconnect.wait()
        self.disconnected = True
        self.connected = False


class TestBrainLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clients = []
        self.scripts = []
        self.tasks = []
        self.patcher = patch("flippy.brain.ClaudeSDKClient", side_effect=self.make_client)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.overrides = patch.multiple("flippy.brain", ENV_MODEL=None, ENV_EFFORT=None)
        self.overrides.start()
        self.addCleanup(self.overrides.stop)
        self.brain = Brain()

    async def asyncTearDown(self):
        for client in self.clients:
            client.release_response.set()
            client.release_disconnect.set()
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.brain.stop()

    def make_client(self, *, options):
        script = self.scripts.pop(0) if self.scripts else {}
        client = Client(options, script.pop("events", success()), **script)
        self.clients.append(client)
        return client

    def task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.append(task)
        return task

    async def next_client(self):
        # A bounded scheduling yield, not a wall-clock sleep or model operation.
        for _ in range(20):
            if self.clients:
                await self.clients[-1].query_started.wait()
                return self.clients[-1]
            await asyncio.sleep(0)
        self.fail("request did not create its mocked client")

    async def test_reset_waits_for_pending_turn_before_disconnect(self):
        self.scripts.append({"blocked": True})
        ask = self.task(self.brain.ask("question", "image", (80, 40)))
        first = await self.next_client()
        reset = self.task(self.brain.reset())
        await asyncio.sleep(0)
        self.assertFalse(first.disconnect_started.is_set())
        self.assertEqual(len(self.clients), 1)
        first.release_response.set()
        self.assertEqual(await ask, "finished")
        await reset
        self.assertTrue(first.disconnected)
        self.assertEqual(len(self.clients), 2)
        self.assertIs(self.brain.client, self.clients[1])

    async def test_cancel_finishes_disconnect_before_next_turn_starts(self):
        self.scripts.append({"blocked": True, "cleanup_blocked": True})
        ask = self.task(self.brain.ask("old", "old-image", (80, 40)))
        first = await self.next_client()
        ask.cancel()
        await first.disconnect_started.wait()
        next_turn = self.task(self.brain.ask("new", "new-image", (80, 40)))
        await asyncio.sleep(0)
        self.assertEqual(len(self.clients), 1)
        self.assertFalse(ask.done())
        first.release_disconnect.set()
        with self.assertRaises(asyncio.CancelledError):
            await ask
        self.assertEqual(await next_turn, "finished")
        self.assertTrue(first.disconnected)
        self.assertEqual(len(self.clients), 2)
        self.assertIn("new", self.clients[1].queries[0][0]["message"]["content"][-1]["text"])

    async def test_canceled_partial_reply_discards_its_client(self):
        partial = StreamEvent("fixture", "fixture", {
            "type": "content_block_delta", "delta": {"type": "text_delta", "text": "partial"}})
        self.scripts.append({"blocked": True, "events": [partial] + success()})
        seen = []
        ask = self.task(self.brain.ask("old", "image", (80, 40), seen.append))
        first = await self.next_client()
        await asyncio.sleep(0)
        self.assertEqual(seen, ["partial"])
        ask.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await ask
        self.assertIsNone(self.brain.client)
        self.assertTrue(first.disconnected)
        self.assertEqual(await self.brain.ask("next", "image", (80, 40)), "finished")
        self.assertIsNot(first, self.brain.client)

    async def test_completed_turn_reuses_transport_for_followup(self):
        self.assertEqual(await self.brain.ask("first", "image", (80, 40)), "finished")
        first = self.brain.client
        self.assertEqual(await self.brain.ask("followup", "image", (80, 40)), "finished")
        self.assertIs(self.brain.client, first)
        self.assertEqual(len(first.queries), 2)
        self.assertFalse(first.disconnected)
        self.assertEqual(self.brain.last_model, "fixture-model")

    async def test_model_change_replaces_completed_transport(self):
        await self.brain.ask("first", "image", (80, 40))
        first = self.brain.client
        self.brain.configure("different-fixture-model", "high")
        self.assertTrue(self.brain.dirty)
        await self.brain.ask("new model", "image", (80, 40))
        self.assertTrue(first.disconnected)
        self.assertEqual(len(self.clients), 2)
        self.assertEqual(self.clients[1].options.model, "different-fixture-model")

    async def test_video_frames_precede_current_screen_and_have_no_tools(self):
        await self.brain.ask("review", "current", (80, 40),
                             extra_images=[("00:01", "first"), ("00:02", "second")])
        client = self.brain.client
        content = client.queries[0][0]["message"]["content"]
        self.assertEqual([item["source"]["data"] for item in content if item["type"] == "image"],
                         ["first", "second", "current"])
        self.assertEqual([item["text"] for item in content[:4] if item["type"] == "text"], ["00:01", "00:02"])
        self.assertIn("current screenshot is 80x40", content[-1]["text"])
        self.assertEqual(client.options.tools, [])
        self.assertEqual(client.options.allowed_tools, [])
        self.assertEqual(client.options.mcp_servers, {})
        self.assertEqual(client.options.setting_sources, [])
        self.assertTrue(client.options.strict_mcp_config)

    async def test_failed_reply_discards_client(self):
        self.scripts.append({"events": [ResultMessage(subtype="error", duration_ms=1,
                            duration_api_ms=1, is_error=True, num_turns=1,
                            session_id="fixture", result="fixture failure")]})
        with self.assertRaises(BrainError):
            await self.brain.ask("question", "image", (80, 40))
        self.assertTrue(self.clients[0].disconnected)
        self.assertIsNone(self.brain.client)

    async def test_missing_or_unsuccessful_terminal_discards_partial_reply(self):
        assistant = AssistantMessage([TextBlock("partial")], "fixture-model")
        for terminal in (None, ResultMessage(subtype="error_max_turns", duration_ms=1,
                        duration_api_ms=1, is_error=False, num_turns=1, session_id="fixture")):
            with self.subTest(terminal=terminal):
                self.scripts.append({"events": [assistant] + ([terminal] if terminal else [])})
                with self.assertRaises(BrainError):
                    await self.brain.ask("question", "image", (80, 40))
                self.assertIsNone(self.brain.client)
                self.assertTrue(self.clients[-1].disconnected)

    async def test_action_missing_or_unsuccessful_terminal_is_not_success(self):
        desktop = SimpleNamespace(server=lambda: {}, cancel=threading.Event(), failure=None)
        assistant = AssistantMessage([TextBlock("partial")], "fixture-model")
        for terminal in (None, ResultMessage(subtype="error_max_turns", duration_ms=1,
                        duration_api_ms=1, is_error=False, num_turns=1, session_id="fixture")):
            with self.subTest(terminal=terminal):
                self.scripts.append({"events": [assistant] + ([terminal] if terminal else [])})
                with self.assertRaises(BrainError):
                    await self.brain.act("fixture task", desktop)
                self.assertTrue(self.clients[-1].disconnected)


if __name__ == "__main__":
    unittest.main()
