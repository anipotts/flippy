"""Native connection choice never silently switches subscriptions or shares history."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from flippy.providers import Brain, ProviderChoiceRequired, CONNECTION_STATUS, setup_ready


class TestProviders(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.values = {('provider', 'mode'): 'auto', ('codex', 'model'): 'default', ('codex', 'effort'): 'medium'}
        self.patch = patch('flippy.providers.settings.get', side_effect=lambda s, k: self.values[(s, k)])
        self.patch.start()
        self.addCleanup(self.patch.stop)
        previous = dict(CONNECTION_STATUS)
        self.addCleanup(lambda: CONNECTION_STATUS.update(previous))
        self.brain = object.__new__(Brain)
        self.brain.providers = {name: SimpleNamespace(start=AsyncMock(), stop=AsyncMock(), available=AsyncMock(return_value=False),
            configure=Mock(), ask=AsyncMock(return_value=name), last_model=name) for name in ('claude', 'codex')}
        self.brain.selected = None
        self.brain.dirty = False
        self.brain._revision = 0
        import asyncio
        self.brain._lock = asyncio.Lock()

    async def test_only_claude_connection_selected_without_codex_inference(self):
        with patch('flippy.providers.claude_available', AsyncMock(return_value=True)):
            self.assertEqual(await self.brain.ask('question', 'image', (10, 10)), 'claude')
        self.brain.providers['codex'].ask.assert_not_called()

    async def test_only_codex_subscription_selected(self):
        self.brain.providers['codex'].available.return_value = True
        with patch('flippy.providers.claude_available', AsyncMock(return_value=False)):
            await self.brain.start()
        self.assertEqual(self.brain.selected, 'codex')

    async def test_both_or_neither_require_choice_without_inference(self):
        for connected in (True, False):
            self.brain.providers['codex'].available.return_value = connected
            with patch('flippy.providers.claude_available', AsyncMock(return_value=connected)):
                with self.assertRaises(ProviderChoiceRequired):
                    await self.brain.ask('question', 'image', (10, 10))
        for provider in self.brain.providers.values():
            provider.ask.assert_not_called()

    async def test_explicit_disconnected_codex_never_falls_back(self):
        self.values[('provider', 'mode')] = 'codex'
        with self.assertRaises(ProviderChoiceRequired):
            await self.brain.start()
        self.brain.providers['claude'].start.assert_not_called()

    async def test_provider_change_closes_previous_transport(self):
        self.brain.selected = 'claude'
        self.brain.dirty = True
        self.values[('provider', 'mode')] = 'codex'
        self.brain.providers['codex'].available.return_value = True
        await self.brain.start()
        self.brain.providers['claude'].stop.assert_awaited_once()
        self.assertEqual(self.brain.selected, 'codex')

    def test_setup_needs_choice_when_both_connected(self):
        CONNECTION_STATUS.update(claude=True, codex=True)
        self.assertFalse(setup_ready())
        self.values[('provider', 'mode')] = 'claude'
        self.assertTrue(setup_ready())

    async def test_provider_change_during_auth_probe_cannot_restore_old_choice(self):
        import asyncio
        entered, release = asyncio.Event(), asyncio.Event()
        self.values[('provider', 'mode')] = 'claude'
        async def slow_claude():
            entered.set()
            await release.wait()
            return True
        self.brain.providers['codex'].available.return_value = True
        with patch('flippy.providers.claude_available', slow_claude):
            task = asyncio.create_task(self.brain.start())
            await entered.wait()
            self.values[('provider', 'mode')] = 'codex'
            self.brain.configure()
            release.set()
            await task
        self.assertEqual(self.brain.selected, 'codex')
        self.brain.providers['claude'].start.assert_not_called()
