"""Codex protocol fixtures, without credentials, model calls or native input."""
import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from flippy.actions import DesktopTools
from flippy.frames import ScreenFrame
from flippy import codex_provider, usage_guard
from flippy.codex_provider import (CodexError, CodexProvider, RUNTIME_UNAVAILABLE, SAFE_CONFIG, _RPC,
                                   _new_enough, _toml_key, child_environment)
from flippy.usage_guard import PlanLimitReached


class FakeRPC:
    def __init__(self, account="chatgpt", status="completed"):
        self.account, self.status = account, status
        self.events = asyncio.Queue()
        self.requests, self.sent, self.threads, self.turns = [], [], [], []
        self.closed, self.cwd = False, "/fixture/flippy"
        self.mcp_servers, self.inventory = {}, []
        self.ephemeral = True
        self.turn_events = None
        # account/rateLimits/read: included usage available, a quiet window
        self.usage = {"ordinaryUsageAllowed": True, "rateLimitsByLimitId": None,
                      "rateLimits": {"primary": {"usedPercent": 12, "resetsAt": 1900000000}, "secondary": None}}

    async def request(self, method, params, timeout=10):
        self.requests.append((method, params))
        if method == "initialize":
            return {"userAgent": "fixture/0.153.4"}
        if method == "account/read":
            return {"account": {"type": self.account, "planType": "plus", "email": None}}
        if method == "account/rateLimits/read":
            return self.usage
        if method == "config/read":
            return {"config": {"model_provider": "openai", "mcp_servers": self.mcp_servers,
                               "openai_base_url": getattr(self, "base_url", None)}}
        if method == "thread/start":
            self.threads.append(params)
            return {"thread": {"id": f"thread{len(self.threads)}", "ephemeral": self.ephemeral},
                    "modelProvider": "openai", "model": "fixture-model", "instructionSources": []}
        if method == "mcpServerStatus/list":
            return {"data": self.inventory, "nextCursor": None}
        if method == "model/list":
            return {"data": [{"id": "fixture-old", "model": "fixture-old", "isDefault": False},
                             {"id": "fixture-default", "model": "fixture-default", "isDefault": True}],
                     "nextCursor": None}
        if method == "turn/start":
            self.turns.append(params)
            thread, turn = params["threadId"], f"turn{len(self.turns)}"
            events = self.turn_events(thread, turn) if self.turn_events else self.reply(thread, turn)
            for event in events:
                await self.events.put(event)
            return {"turn": {"id": turn, "status": "inProgress"}}
        if method == "turn/interrupt":
            await self.events.put(self.completed(params["threadId"], params["turnId"], "interrupted"))
            return {}
        raise AssertionError(method)

    def reply(self, thread, turn):
        return [
            {"method": "item/agentMessage/delta", "params": {
                "threadId": thread, "turnId": turn, "itemId": "answer", "delta": "Click [POINT:12,"}},
            {"method": "item/agentMessage/delta", "params": {
                "threadId": thread, "turnId": turn, "itemId": "answer", "delta": "34:menu]."}},
            {"method": "item/completed", "params": {
                "threadId": thread, "turnId": turn,
                "item": {"type": "agentMessage", "id": "answer", "text": "Click [POINT:12,34:menu].",
                         "phase": "final_answer"}}},
            self.completed(thread, turn, self.status),
        ]

    @staticmethod
    def completed(thread, turn, status):
        return {"method": "turn/completed", "params": {"threadId": thread,
                "turn": {"id": turn, "status": status, "error": None}}}

    @staticmethod
    def tool(thread, turn, name, args, call_id="tool1"):
        return {"id": call_id, "method": "item/tool/call", "params": {
            "threadId": thread, "turnId": turn, "callId": call_id, "tool": name,
            "arguments": args, "namespace": None}}

    async def send(self, message):
        self.sent.append(message)

    async def close(self):
        self.closed = True


class TestCodexProvider(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rpc = FakeRPC()
        self.launch = patch("flippy.codex_provider._RPC.launch", return_value=self.rpc).start()
        self.cli_probe = patch("flippy.codex_provider._cli_logged_in", return_value=False).start()
        self.addCleanup(patch.stopall)
        usage_guard.GUARDS["codex"] = usage_guard.Guard("codex")  # each test starts with no limit known
        self.provider = CodexProvider()
        self.addAsyncCleanup(self.provider.stop)

    def allow_fixture_turns(self):
        """Turns run when the fixture's usage report says included usage is available (the default)."""

    def desktop(self, *, capture=None, approve=None):
        self.performed, self.approved = [], []

        async def default_capture():
            return ScreenFrame("Zml4dHVyZQ==", (100, 100), (100, 100),
                               ("com.flippy.fixture", 1, 1, (0, 0, 100, 100), 0))

        async def default_approve(name, args, shot):
            self.approved.append(name)
            return True

        async def perform(name, args, shot, cancel):
            self.performed.append(name)

        return DesktopTools(capture or default_capture, approve or default_approve, perform, max_text=2000)

    async def test_no_included_usage_left_sends_no_user_content_or_model_request(self):
        self.rpc.usage = {"ordinaryUsageAllowed": False,
                          "rateLimits": {"primary": {"usedPercent": 100, "resetsAt": 1900000000}}}
        await self.provider.start()
        for operation in (
            lambda: self.provider.ask("private question", "private image", (100, 100)),
            lambda: self.provider.act("private task", self.desktop()),
            lambda: self.provider.write_tips("app", "goal", 1, []),
        ):
            with self.assertRaises(PlanLimitReached) as raised:
                await operation()
            self.assertIn("never uses ChatGPT credits", str(raised.exception))
        self.assertIn("account/rateLimits/read", [method for method, _ in self.rpc.requests])
        self.assertFalse(self.rpc.threads)
        self.assertFalse(self.rpc.turns)

    async def test_nearly_used_up_window_refuses_before_the_limit(self):
        self.rpc.usage = {"ordinaryUsageAllowed": True,
                          "rateLimits": {"primary": {"usedPercent": 96, "resetsAt": 1900000000}}}
        with self.assertRaises(PlanLimitReached):
            await self.provider.ask("q", "image", (100, 100))
        self.assertFalse(self.rpc.turns)

    async def test_limit_reached_mid_request_stops_it(self):
        def events(thread, turn):
            return [{"method": "item/agentMessage/delta", "params": {
                        "threadId": thread, "turnId": turn, "itemId": "a", "delta": "Click"}},
                    {"method": "account/rateLimits/updated", "params": {"rateLimits": {
                        "rateLimitReachedType": "rate_limit_reached",
                        "primary": {"usedPercent": 100, "resetsAt": 1900000000}}}}]
        self.rpc.turn_events = events
        with self.assertRaises(PlanLimitReached):
            await self.provider.ask("q", "image", (100, 100))
        self.assertIn("turn/interrupt", [method for method, _ in self.rpc.requests])
        with self.assertRaises(PlanLimitReached):  # and nothing more until it resets
            await self.provider.ask("again", "image", (100, 100))
        self.assertEqual(len(self.rpc.turns), 1)

    def test_server_names_are_bare_toml_keys_when_they_can_be(self):
        # Codex 0.159 reads a quoted segment literally: mcp_servers."node_repl" became a new, broken server
        self.assertEqual(_toml_key("node_repl"), "node_repl")
        self.assertEqual(_toml_key("computer-use"), "computer-use")
        self.assertEqual(_toml_key("my server.v2"), '"my server.v2"')

    def test_tools_reach_the_model_but_it_cant_run_code(self):
        # Codex 0.159 hands dynamic tools to the model through code_mode_host: off, /act never saw a tool
        self.assertNotIn("features.code_mode_host", SAFE_CONFIG)
        for off in ("code_mode", "code_mode_only", "shell_tool", "apps", "connectors", "plugins", "computer_use"):
            self.assertIs(SAFE_CONFIG[f"features.{off}"], False, off)

    def test_the_api_endpoint_is_not_pinned(self):
        # pinning it sends ChatGPT-login requests to the API endpoint on Codex 0.159, which refuses them (401)
        self.assertNotIn("openai_base_url", SAFE_CONFIG)
        self.assertEqual(SAFE_CONFIG["chatgpt_base_url"], "https://chatgpt.com/backend-api/")

    async def test_a_config_that_redirects_requests_is_refused(self):
        self.rpc.base_url = "https://proxy.example/v1"
        with self.assertRaises(CodexError):
            await self.provider.ask("q", "image", (100, 100))
        self.assertFalse(self.rpc.turns)

    def test_codex_is_found_outside_the_minimal_app_path(self):
        # apps opened from the Dock get PATH=/usr/bin:/bin:/usr/sbin:/sbin; Homebrew's codex isn't on it
        from flippy import codex_provider
        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, "codex")
            with open(fake, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(fake, 0o755)
            with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}), patch.object(codex_provider, "CODEX_DIRS", (tmp,)):
                self.assertEqual(codex_provider.codex_executable(), fake)
                self.assertTrue(codex_provider.child_environment()["PATH"].startswith(tmp))

    def test_codex_from_nvm_is_found_newest_node_first(self):
        # Linux: npm i -g under nvm puts codex in ~/.nvm/versions/node/<v>/bin, never on a shortcut's PATH
        from flippy import codex_provider
        with tempfile.TemporaryDirectory() as home:
            for v in ("v9.0.0", "v24.11.1", "v18.2.0"):
                os.makedirs(os.path.join(home, ".nvm", "versions", "node", v, "bin"))
            for v in ("v9.0.0", "v24.11.1"):
                fake = os.path.join(home, ".nvm", "versions", "node", v, "bin", "codex")
                with open(fake, "w") as f:
                    f.write("#!/bin/sh\n")
                os.chmod(fake, 0o755)
            with patch.dict(os.environ, {"PATH": "/usr/bin:/bin", "HOME": home}), \
                    patch.object(codex_provider, "CODEX_DIRS", ()):
                self.assertEqual(codex_provider.codex_executable(),
                                 os.path.join(home, ".nvm", "versions", "node", "v24.11.1", "bin", "codex"))

    def test_newer_codex_versions_are_accepted(self):
        self.assertTrue(_new_enough("codex-cli 0.153.4"))
        self.assertTrue(_new_enough("codex-cli 0.159.2"))
        self.assertTrue(_new_enough("codex-cli 1.0.0"))
        self.assertFalse(_new_enough("codex-cli 0.152.9"))
        self.assertFalse(_new_enough("something else"))

    async def test_available_is_account_only_and_releases_transport(self):
        self.assertTrue(await self.provider.available())
        self.assertTrue(self.rpc.closed)
        self.assertEqual([method for method, _ in self.rpc.requests], ["initialize", "account/read"])
        self.assertIsNone(self.provider.blocked_reason)
        self.assertEqual(self.rpc.sent, [{"method": "initialized"}])
        self.assertEqual(self.launch.call_args.args[0]["forced_login_method"], "chatgpt")

    async def test_api_and_other_auth_are_refused_without_login_or_logout(self):
        for account in ("apiKey", "amazonBedrock", "unknown", None):
            with self.subTest(account=account):
                self.rpc.account = account
                self.assertFalse(await self.provider.available())
        self.assertFalse(self.rpc.turns)
        self.assertFalse(any(method.startswith("account/login") or method == "account/logout"
                             for method, _ in self.rpc.requests))

    async def test_probe_hides_raw_backend_errors(self):
        self.launch.side_effect = RuntimeError("private credential-bearing backend details")
        self.assertFalse(await self.provider.available())
        self.assertNotIn("credential", self.provider.blocked_reason)

    async def test_cli_auth_is_distinct_from_an_unavailable_app_server(self):
        self.launch.side_effect = CodexError("Codex did not respond.")
        self.cli_probe.return_value = True
        # signed in but can't run here: not "connected", so a Claude user isn't asked to pick a Codex that can't answer
        self.assertFalse(await self.provider.available())
        self.assertEqual(self.provider.auth_source, "cli")
        self.assertEqual(self.provider.blocked_reason, RUNTIME_UNAVAILABLE)
        with self.assertRaises(CodexError) as raised:
            await self.provider.start()
        self.assertEqual(raised.exception.safe_message, RUNTIME_UNAVAILABLE)

    async def test_image_stills_streamed_point_and_ephemeral_followup(self):
        self.allow_fixture_turns()
        chunks = []
        text = await self.provider.ask("question", "screen", (1920, 1080), chunks.append,
                                       extra_images=(("first still", "first"), ("second still", "second")))
        self.assertEqual(text, "Click [POINT:12,34:menu].")
        self.assertEqual("".join(chunks), text)
        await self.provider.ask("continue", "updated screen", (1920, 1080))
        self.assertEqual(len(self.rpc.threads), 1)
        self.assertEqual(self.rpc.turns[0]["threadId"], self.rpc.turns[1]["threadId"])
        options = self.rpc.threads[0]
        self.assertTrue(options["ephemeral"])
        self.assertEqual(options["dynamicTools"], [])
        self.assertEqual(options["environments"], [])
        self.assertEqual(options["runtimeWorkspaceRoots"], [])
        self.assertFalse(options["allowProviderModelFallback"])
        self.assertEqual(options["modelProvider"], "openai")
        self.assertEqual([item.get("text") or item.get("url") for item in self.rpc.turns[0]["input"]],
                         ["first still", "data:image/jpeg;base64,first", "second still",
                          "data:image/jpeg;base64,second", "data:image/jpeg;base64,screen",
                          "(screenshot is 1920x1080 pixels)\n\nquestion"])
        self.assertTrue(all(turn["environments"] == [] for turn in self.rpc.turns))
        self.assertEqual(self.provider.last_model, "fixture-model")

    async def test_failed_and_interrupted_terminal_states_never_return_partial_success(self):
        self.allow_fixture_turns()
        for status in ("failed", "interrupted"):
            with self.subTest(status=status):
                self.rpc.status = status
                with self.assertRaises(CodexError):
                    await self.provider.ask("question", "image", (100, 100))
                self.assertTrue(self.rpc.closed)
                self.assertIsNone(self.provider._thread)

    async def test_action_catalog_and_responses_use_the_shared_runtime_limits(self):
        self.allow_fixture_turns()
        tools = self.desktop()
        calls = [("screenshot", {}), ("click", {"x": 1, "y": 2, "reason": "open"}),
                 ("type", {"text": "hello", "reason": "write"}),
                 ("key", {"combo": "tab", "reason": "move"}),
                 ("scroll", {"x": 1, "y": 2, "direction": "down", "lines": 2, "reason": "read"}),
                 ("drag", {"x": 1, "y": 2, "to_x": 3, "to_y": 4, "modifiers": [], "reason": "move"})]
        self.rpc.turn_events = lambda thread, turn: [
            *[self.rpc.tool(thread, turn, name, args, f"tool{i}") for i, (name, args) in enumerate(calls)],
            *self.rpc.reply(thread, turn),
        ]
        await self.provider.act("task", tools)
        advertised = {tool["name"]: tool for tool in self.rpc.threads[0]["dynamicTools"]}
        self.assertEqual(set(advertised), set(tools.catalog()))
        self.assertEqual(advertised["type"]["inputSchema"]["properties"]["text"]["maxLength"], 2000)
        self.assertEqual(self.performed, [name for name, _ in calls if name != "screenshot"])
        responses = [message["result"] for message in self.rpc.sent if "result" in message]
        self.assertEqual(len(responses), 6)
        self.assertTrue(all(result["success"] for result in responses))
        self.assertTrue(all(result["contentItems"][1]["type"] == "inputImage" for result in responses))
        self.assertTrue(all(result["contentItems"][1]["imageUrl"].startswith("data:image/jpeg;base64,")
                            for result in responses))

    async def test_decline_interrupts_and_never_executes_queued_action(self):
        self.allow_fixture_turns()

        async def decline(*args):
            return False

        tools = self.desktop(approve=decline)
        self.rpc.turn_events = lambda thread, turn: [
            self.rpc.tool(thread, turn, "screenshot", {}, "first"),
            self.rpc.tool(thread, turn, "key", {"combo": "tab", "reason": "move"}, "declined"),
            self.rpc.tool(thread, turn, "type", {"text": "never", "reason": "write"}, "queued"),
        ]
        with self.assertRaises(CodexError):
            await self.provider.act("task", tools)
        self.assertEqual(self.performed, [])
        declined = next(item for item in self.rpc.sent if item.get("id") == "declined")
        self.assertFalse(declined["result"]["success"])
        queued = next(item for item in self.rpc.sent if item.get("id") == "queued")
        self.assertIn("error", queued)
        self.assertTrue(self.rpc.closed)

    async def test_screenshot_calls_are_also_bounded_by_the_task_tool_limit(self):
        self.allow_fixture_turns()
        tools = self.desktop()
        tools.max_turns = 2
        self.rpc.turn_events = lambda thread, turn: [
            self.rpc.tool(thread, turn, "screenshot", {}, f"shot{i}") for i in range(3)]
        with self.assertRaises(CodexError) as raised:
            await self.provider.act("task", tools)
        self.assertIn("tool limit", raised.exception.safe_message)
        responses = [item["result"] for item in self.rpc.sent if "result" in item]
        self.assertEqual([item["success"] for item in responses], [True, True, False])
        self.assertTrue(self.rpc.closed)

    async def test_stop_during_outstanding_tool_answers_server_then_awaits_interruption(self):
        self.allow_fixture_turns()
        started = asyncio.Event()

        async def capture():
            started.set()
            await asyncio.Event().wait()

        tools = self.desktop(capture=capture)
        self.rpc.turn_events = lambda thread, turn: [self.rpc.tool(thread, turn, "screenshot", {}, "pending")]
        task = asyncio.create_task(self.provider.act("task", tools))
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.wait_for(self.provider.stop(), 2)
        self.assertTrue(task.cancelled())
        self.assertTrue(tools.cancel.is_set())
        self.assertTrue(self.rpc.closed)
        self.assertFalse(next(item for item in self.rpc.sent if item.get("id") == "pending")["result"]["success"])
        self.assertEqual(self.rpc.requests[-1][0], "turn/interrupt")
        self.assertTrue(self.rpc.events.empty())

    async def test_ordinary_mode_rejects_server_tool_requests(self):
        self.allow_fixture_turns()
        self.rpc.turn_events = lambda thread, turn: [self.rpc.tool(thread, turn, "screenshot", {})]
        with self.assertRaises(CodexError):
            await self.provider.ask("question", "image", (100, 100))
        self.assertIn("error", next(item for item in self.rpc.sent if item.get("id") == "tool1"))
        self.assertTrue(self.rpc.closed)

    async def test_non_ephemeral_or_inherited_mcp_tools_prevent_turn_start(self):
        self.allow_fixture_turns()
        self.rpc.ephemeral = False
        with self.assertRaises(CodexError):
            await self.provider.ask("question", "image", (100, 100))
        self.rpc.ephemeral = True
        self.rpc.inventory = [{"tools": {"inherited_tool": {}}, "resources": [], "resourceTemplates": []}]
        with self.assertRaises(CodexError):
            await self.provider.ask("question", "image", (100, 100))
        self.assertFalse(self.rpc.turns)

    async def test_inherited_mcp_map_is_disabled_by_id_on_a_fresh_transport(self):
        self.allow_fixture_turns()
        self.rpc.mcp_servers = {"legacy.with.dot": {"command": "credential-bearing value", "enabled": True}}
        isolated = FakeRPC()
        isolated.mcp_servers = {"legacy.with.dot": {"enabled": False}}
        self.launch.side_effect = [self.rpc, isolated]
        await self.provider.ask("question", "image", (100, 100))
        overrides = self.launch.call_args.args[0]
        self.assertIs(overrides['mcp_servers."legacy.with.dot".enabled'], False)
        self.assertNotIn("credential-bearing", str(overrides))
        self.assertTrue(self.rpc.closed)
        self.assertTrue(isolated.turns)

    async def test_tips_use_a_separate_ephemeral_tool_free_thread(self):
        self.allow_fixture_turns()
        await self.provider.ask("question", "image", (100, 100))
        tutor = self.provider._thread
        self.rpc.turn_events = lambda thread, turn: [
            {"method": "item/completed", "params": {"threadId": thread, "turnId": turn,
             "item": {"id": "tips", "type": "agentMessage", "phase": "final_answer",
                      "text": '[{"text":"Use the menu.","level":1}]'}}}, self.rpc.completed(thread, turn, "completed")]
        tips = await self.provider.write_tips("app", "goal", 1, ["known tip"])
        self.assertEqual(tips, [{"text": "Use the menu.", "level": 1}])
        self.assertNotEqual(self.rpc.turns[-1]["threadId"], tutor)
        self.assertEqual(self.rpc.threads[-1]["dynamicTools"], [])
        self.assertEqual(self.provider._thread, tutor)

    async def test_canceled_partial_reply_is_replayed_in_a_new_in_memory_chat(self):
        self.allow_fixture_turns()
        streamed = asyncio.Event()
        self.rpc.turn_events = lambda thread, turn: [
            {"method": "item/agentMessage/delta", "params": {
                "threadId": thread, "turnId": turn, "itemId": "partial", "delta": "partial reply"}}]
        task = asyncio.create_task(self.provider.ask("original question", "original image", (100, 100),
                                                      lambda delta: streamed.set()))
        await asyncio.wait_for(streamed.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.provider.replay_context)
        self.assertEqual(self.provider.history, [("original question", "partial reply [Reply interrupted by user.]")])
        self.rpc.turn_events = None
        await self.provider.ask("continue", "new image", (100, 100))
        preface = self.rpc.turns[-1]["input"][0]["text"]
        self.assertIn("original question", preface)
        self.assertIn("partial reply [Reply interrupted by user.]", preface)
        self.assertNotIn("original image", preface)
        self.assertNotEqual(self.rpc.turns[-1]["threadId"], self.rpc.turns[0]["threadId"])
        await self.provider.stop()
        self.assertEqual(self.provider.history, [])
        self.assertEqual(self.provider.partial, "")

    async def test_default_means_codexs_default_not_a_model_left_in_the_users_config(self):
        # ~/.codex/config.toml from an older Codex named gpt-5.1-codex-max, which ChatGPT accounts can't use
        self.allow_fixture_turns()
        await self.provider.ask("question", "screen", (100, 100))
        self.assertEqual(self.rpc.threads[-1]["model"], "fixture-default")
        await self.provider.stop()
        self.provider.configure("chosen-model", "medium")  # a model picked in Settings is used as it is
        await self.provider.ask("question", "screen", (100, 100))
        self.assertEqual(self.rpc.threads[-1]["model"], "chosen-model")

    def test_memory_retention_is_bounded_and_configuration_clears_it(self):
        for _ in range(20):
            self.provider._remember("q" * 10000, "a" * 20000)
        self.assertLessEqual(sum(len(q) + len(a) for q, a in self.provider.history), 24000)
        self.assertTrue(all(len(q) <= 6000 and len(a) <= 12000 for q, a in self.provider.history))
        self.provider.configure("other-model", "medium")
        self.assertEqual(self.provider.history, [])


class TestEnvironment(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")

    def test_child_environment_drops_api_billing_and_custom_routing(self):
        with patch.dict(os.environ, {"HOME": self.home, "PATH": "/fixture/bin",
             "OPENAI_API_KEY": "fixture", "CODEX_API_KEY": "fixture", "CODEX_HOME": "/other/login",
             "OPENAI_BASE_URL": "https://example.invalid", "HTTPS_PROXY": "fixture",
             "ANTHROPIC_API_KEY": "fixture", "NODE_OPTIONS": "fixture"}, clear=True):
            env = child_environment()
            self.assertEqual(set(env), {"HOME", "PATH", "CODEX_HOME"})   # no keys, proxies or base URLs
            self.assertEqual(env["HOME"], self.home)
            self.assertIn("/fixture/bin", env["PATH"].split(os.pathsep))  # the user's PATH, plus Codex's install dirs
        self.assertEqual(SAFE_CONFIG["history.persistence"], "none")
        self.assertEqual(SAFE_CONFIG["model_provider"], "openai")
        self.assertFalse(SAFE_CONFIG["features.shell_tool"])
        self.assertFalse(SAFE_CONFIG["features.plugins"])

    def test_codex_runs_in_flippys_own_home_never_the_users(self):
        # The user's Codex setup (config.toml, AGENTS.md, plugins, MCP servers) lives in ~/.codex or $CODEX_HOME;
        # Flippy's Codex has a home of its own, per profile, private to the user.
        for profile, slug in (("default", "flippy"), ("demo", "flippy-demo")):
            with self.subTest(profile), patch.dict(os.environ, {"HOME": self.home, "PATH": "/usr/bin",
                                                                "CODEX_HOME": os.path.join(self.home, ".codex"),
                                                                "FLIPPY_PROFILE": profile}, clear=True):
                home = child_environment()["CODEX_HOME"]
                self.assertEqual(home, os.path.join(self.home, ".config", slug, "codex"))
                self.assertTrue(os.path.isdir(home))
                self.assertEqual(os.stat(home).st_mode & 0o777, 0o700)

    def test_signing_in_signs_in_flippys_codex(self):
        with patch.dict(os.environ, {"HOME": self.home, "PATH": "/usr/bin", "XDG_CONFIG_HOME": self.home + "/my cfg"},
                        clear=True):
            command = codex_provider.login_command("/opt/my codex/codex")
            home = child_environment()["CODEX_HOME"]
        import shlex
        self.assertIn("export CODEX_HOME=" + shlex.quote(home), command)
        self.assertIn("unset OPENAI_API_KEY CODEX_API_KEY", command)
        self.assertTrue(command.endswith(shlex.quote("/opt/my codex/codex") + " -c 'forced_login_method=\"chatgpt\"' login"))
        self.assertEqual(shlex.split(command.split("; ")[1])[1], "CODEX_HOME=" + home)  # a path with spaces survives


class TestIsolationReasons(unittest.TestCase):
    def test_the_log_says_which_check_refused_and_the_user_sees_one_sentence(self):
        from flippy import errors
        shown, logged = errors.describe(codex_provider._not_isolated("instruction_sources"))
        self.assertEqual(shown, errors.say("CODEX-ISOLATION"))
        self.assertIn("(instruction_sources)", logged)


class TestStdio(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_demultiplexes_reversed_responses_and_notifications(self):
        directory = tempfile.TemporaryDirectory(prefix="flippy-rpc-test-")
        code = """
import json,sys
a=json.loads(sys.stdin.readline()); b=json.loads(sys.stdin.readline())
print(json.dumps({'method':'fixture/event','params':{}}),flush=True)
for message in (b,a):
 print(json.dumps({'id':message['id'],'result':{'method':message['method']}}),flush=True)
for line in sys.stdin: pass
"""
        process = await asyncio.create_subprocess_exec(sys.executable, "-u", "-c", code,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL)
        rpc = _RPC(process, directory)
        try:
            first, second = await asyncio.gather(rpc.request("first", {}), rpc.request("second", {}))
            self.assertEqual(first, {"method": "first"})
            self.assertEqual(second, {"method": "second"})
            self.assertEqual((await rpc.events.get())["method"], "fixture/event")
        finally:
            await rpc.close()
        self.assertIsNotNone(process.returncode)
        self.assertFalse(os.path.exists(directory.name))

    async def test_invalid_stdio_packet_fails_pending_request_without_raw_details(self):
        directory = tempfile.TemporaryDirectory(prefix="flippy-rpc-test-")
        process = await asyncio.create_subprocess_exec(sys.executable, "-u", "-c",
                    "import sys;sys.stdin.readline();print('private malformed backend packet',flush=True)",
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL)
        rpc = _RPC(process, directory)
        try:
            with self.assertRaises(CodexError) as raised:
                await rpc.request("request", {})
            self.assertNotIn("private", raised.exception.safe_message)
        finally:
            await rpc.close()


if __name__ == "__main__":
    unittest.main()
