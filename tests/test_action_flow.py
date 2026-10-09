"""Exercise controller approval scope and capture retries without native input."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, AsyncMock

from flippy.actions import ActionError, ApprovalPolicy, approval_text
from flippy.frames import ScreenFrame


def controller(mode='per_app', remembered=()):
    tree = ast.parse((Path(__file__).parents[1] / 'flippy/daemon.py').read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Flippy')
    namespace = {'asyncio': asyncio, 'ActionError': ActionError, 'approval_text': approval_text,
                 'loop': SimpleNamespace(idle_add=lambda fn: fn()),
                 'settings': SimpleNamespace(get=lambda *args: list(remembered), set=Mock())}
    names = ('_action_approve', '_capture_frame')
    for node in cls.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name in names:
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<action flow>', 'exec'), namespace)
    obj = type('Controller', (), {name: namespace[name] for name in names})()
    obj.action_policy = ApprovalPolicy(mode)
    obj.request = object()
    obj._owns = Mock(return_value=True)
    obj._acting = Mock()
    async def main(fn, req=None):
        return fn()
    obj._action_main = main
    obj.overlay = SimpleNamespace(point=Mock(), queue_draw=Mock(), show_text=Mock())
    obj.ui = SimpleNamespace(action_card=SimpleNamespace(card=Mock(), hide=Mock()))
    return obj, namespace


def frame(app='com.apple.TextEdit'):
    return ScreenFrame('jpeg', (100, 100), (100, 100),
                       (app, 42, 7, (10, 10, 60, 60), (1, (100, 100))))


class TestApprovalFlow(unittest.IsolatedAsyncioTestCase):
    async def approve(self, obj, shot, point, button='Allow once'):
        def choose(title, text, buttons, **kwargs):
            next(callback for label, callback in buttons if label == button)()
        obj.ui.action_card.card.side_effect = choose
        return await asyncio.wait_for(obj._action_approve('click',
            {'x': point[0], 'y': point[1], 'reason': 'fixture'}, shot, obj.request), 1)

    async def test_valid_app_grant_bypasses_card(self):
        obj, _ = controller()
        shot = frame()
        obj.action_policy.grant(shot.target)
        self.assertTrue(await self.approve(obj, shot, (30, 30)))
        obj.ui.action_card.card.assert_not_called()

    async def test_outside_window_requires_exact_once_even_with_app_grant(self):
        for mode in ('per_app', 'auto'):
            with self.subTest(mode=mode):
                obj, _ = controller(mode)
                shot = frame()
                obj.action_policy.grant(shot.target)
                self.assertTrue(await self.approve(obj, shot, (90, 90)))
                args = obj.ui.action_card.card.call_args.args
                self.assertEqual([label for label, _ in args[2]], ['Stop', 'Allow once'])
                self.assertIn('"x": 90', args[1])

    async def test_browser_never_bypasses_card_or_offers_persistent_grant(self):
        obj, _ = controller('auto', ['com.apple.Safari'])
        shot = frame('com.apple.Safari')
        obj.action_policy.grant(shot.target)
        self.assertTrue(await self.approve(obj, shot, (30, 30)))
        self.assertEqual([label for label, _ in obj.ui.action_card.card.call_args.args[2]],
                         ['Stop', 'Allow once'])

    async def test_remembered_app_bypasses_only_inside_scope(self):
        obj, _ = controller(remembered=['com.apple.TextEdit'])
        self.assertTrue(await self.approve(obj, frame(), (30, 30)))
        obj.ui.action_card.card.assert_not_called()

    async def test_cancel_during_foreground_retry_never_captures_again(self):
        obj, namespace = controller()
        obj._capture_frame_once = AsyncMock(side_effect=ActionError('The foreground window changed.'))
        obj._owns.return_value = False
        with self.assertRaises(asyncio.CancelledError):
            await obj._capture_frame(obj.request, targeted=True)
        self.assertEqual(obj._capture_frame_once.await_count, 1)
        obj._acting.assert_not_called()

    async def test_permission_error_is_not_retried(self):
        obj, _ = controller()
        obj._capture_frame_once = AsyncMock(side_effect=ActionError('Check Screen Recording permission.'))
        with self.assertRaises(ActionError):
            await obj._capture_frame(obj.request, targeted=True)
        self.assertEqual(obj._capture_frame_once.await_count, 1)
        obj._acting.assert_not_called()
