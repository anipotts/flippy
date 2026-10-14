"""Exercise actual gesture method bodies without importing AppKit or posting input."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class TestGestures(unittest.TestCase):
    def setUp(self):
        source = ast.parse((Path(__file__).parents[1] / 'flippy/mac/ui.py').read_text())
        platform = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'Platform')
        names = ('_gesture', 'drag', 'scroll', 'key', 'type_text', 'click', '_check_physical_input')
        methods = [n for n in platform.body if isinstance(n, ast.FunctionDef) and n.name in names]
        now = [0.0]  # a fake clock: sleep advances it, so the held-input grace period ends without waiting
        clock = SimpleNamespace(monotonic=lambda: now[0],
                                sleep=Mock(side_effect=lambda s: now.__setitem__(0, now[0] + s)))
        namespace = {'__name__': 'flippy.mac.ui', '__package__': 'flippy.mac', 'Quartz': Mock(), 'time': clock,
                     'hotkeys': SimpleNamespace(KEYS={'return': 36, 'a': 0})}
        for n in methods:
            exec(compile(ast.Module(body=[n], type_ignores=[]), '<native gesture>', 'exec'), namespace)
        self.q = namespace['Quartz']
        self.q.CGEventSourceButtonState.return_value = False
        self.q.CGEventSourceKeyState.return_value = False
        for name, value in [('kCGEventMouseMoved',1),('kCGEventLeftMouseDown',2),
                            ('kCGEventLeftMouseDragged',3),('kCGEventLeftMouseUp',4),
                            ('kCGScrollEventUnitLine',5)]:
            setattr(self.q,name,value)
        cls = type('Adapter', (), {name: namespace[name] for name in names})
        self.ui = cls()
        self.ui._can_post = Mock(return_value=None)
        self.ui._mouse = Mock()
        self.ui._gesture_mouse = Mock()
        self.ui._modifier = Mock()
        self.ui.MOD_KEYS = {'cmd':55,'shift':56}
        self.ui.HELD_GRACE_S = 0.4
        self.ui.FLAGS = {'cmd':1,'shift':2}

    def test_drag_straight_path_and_final_release(self):
        self.assertEqual(self.ui.drag(0,0,240,120, ['cmd']), 'ok')
        events = self.ui._gesture_mouse.call_args_list
        self.assertEqual(len(events),26)
        self.assertEqual(events[0].args,(2,0,0,1))
        self.assertEqual(events[12].args,(3,120,60,1))
        self.assertEqual(events[-1].args,(4,240,120,1))
        self.assertEqual(self.ui._modifier.call_args_list[-1].args,('cmd',0))

    def test_failed_mouse_post_still_releases(self):
        def post(kind,*args):
            if kind == 3:
                raise RuntimeError('post failure')
        self.ui._gesture_mouse.side_effect = post
        with self.assertRaises(RuntimeError):
            self.ui.drag(0,0,24,24,['cmd'])
        self.assertEqual(self.ui._gesture_mouse.call_args.args[0],4)
        self.assertEqual(self.ui._modifier.call_args.args,('cmd',0))

    def test_release_failure_attempts_all_cleanup_and_is_explicit(self):
        from flippy.actions import InputCleanupError
        def post(kind, *args):
            if kind == 4:
                raise RuntimeError('release failure')
        self.ui._gesture_mouse.side_effect = post
        with self.assertRaises(InputCleanupError):
            self.ui.drag(0,0,24,24,['cmd','shift'])
        self.assertEqual(self.ui._modifier.call_args_list[-2].args,('shift',1))
        self.assertEqual(self.ui._modifier.call_args_list[-1].args,('cmd',0))

    def test_physical_input_is_not_released(self):
        self.q.CGEventSourceButtonState.return_value=True
        with self.assertRaises(RuntimeError):
            self.ui.drag(0,0,1,1)
        self.ui._gesture_mouse.assert_not_called()

    def test_scroll_directions(self):
        for direction,v,h in [('up',3,0),('down',-3,0),('left',0,3),('right',0,-3)]:
            self.ui.scroll(1,2,direction,3)
            self.assertEqual(self.q.CGEventCreateScrollWheelEvent.call_args.args[-2:],(v,h))

    def test_physical_held_click_posts_no_events(self):
        from flippy.actions import ActionError
        self.q.CGEventSourceButtonState.return_value=True
        with self.assertRaises(ActionError): self.ui.click(10,20)
        self.q.CGEventPost.assert_not_called()

    def test_input_that_lets_go_within_the_grace_period_does_not_stop_it(self):
        # the click on "Allow", or Flippy's own last keystroke, can read as down for a moment
        self.q.CGEventSourceButtonState.side_effect = [True, True, False]
        self.assertEqual(self.ui.click(10, 20), 'ok')
        self.assertTrue(self.q.CGEventPost.called)

    def test_held_input_is_reported_as_held_not_as_a_cleanup_failure(self):
        from flippy.actions import InputHeldError
        self.q.CGEventSourceKeyState.return_value = True
        with self.assertRaises(InputHeldError):
            self.ui.key('return')
        self.q.CGEventPost.assert_not_called()

    def test_physical_held_key_and_typing_post_no_events(self):
        from flippy.actions import ActionError
        self.q.CGEventSourceKeyState.side_effect=lambda state,code: code == 36
        with self.assertRaises(ActionError): self.ui.key('return')
        self.q.CGEventPost.assert_not_called()
        self.q.CGEventSourceKeyState.side_effect=lambda state,code: code == 0
        with self.assertRaises(ActionError): self.ui.type_text('a',wait=True)
        self.q.CGEventPost.assert_not_called()

    def test_physical_modifier_blocks_typing(self):
        from flippy.actions import ActionError
        self.q.CGEventSourceKeyState.side_effect=lambda state,code: code == 55
        with self.assertRaises(ActionError): self.ui.type_text('a',wait=True)
        self.q.CGEventPost.assert_not_called()

    def test_click_post_failure_releases_mouse(self):
        count = 0
        def post(*args):
            nonlocal count
            count += 1
            if count == 2:  # movement succeeds, down may have been delivered
                raise RuntimeError('post failure')
        self.q.CGEventPost.side_effect = post
        with self.assertRaises(RuntimeError):
            self.ui.click(10,20)
        self.assertEqual([c.args[1] for c in self.q.CGEventCreateMouseEvent.call_args_list],[1,2,4])

    def test_typing_post_failure_releases_key(self):
        count = 0
        def post(*args):
            nonlocal count
            count += 1
            if count == 1:
                raise RuntimeError('post failed after possible delivery')
        self.q.CGEventPost.side_effect = post
        with self.assertRaises(RuntimeError):
            self.ui.type_text('a', wait=True)
        self.assertEqual([c.args[-1] for c in self.q.CGEventCreateKeyboardEvent.call_args_list],[True,False])
