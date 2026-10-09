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
        methods = [n for n in platform.body if isinstance(n, ast.FunctionDef)
                   and n.name in ('_gesture', 'drag', 'scroll', 'key')]
        namespace = {'Quartz': Mock(), 'time': SimpleNamespace(sleep=Mock()),
                     'hotkeys': SimpleNamespace(KEYS={'return': 36})}
        for n in methods:
            exec(compile(ast.Module(body=[n], type_ignores=[]), '<native gesture>', 'exec'), namespace)
        self.q = namespace['Quartz']
        self.q.CGEventSourceButtonState.return_value = False
        self.q.CGEventSourceKeyState.return_value = False
        for name, value in [('kCGEventMouseMoved',1),('kCGEventLeftMouseDown',2),
                            ('kCGEventLeftMouseDragged',3),('kCGEventLeftMouseUp',4),
                            ('kCGScrollEventUnitLine',5)]:
            setattr(self.q,name,value)
        cls = type('Adapter', (), {name: namespace[name] for name in ('_gesture','drag','scroll','key')})
        self.ui = cls()
        self.ui._can_post = Mock(return_value=None)
        self.ui._mouse = Mock()
        self.ui._gesture_mouse = Mock()
        self.ui._modifier = Mock()
        self.ui.MOD_KEYS = {'cmd':55,'shift':56}
        self.ui.FLAGS = {'cmd':1,'shift':2}

    def test_drag_straight_path_and_final_release(self):
        self.assertEqual(self.ui.drag(0,0,240,120, ['cmd']), 'ok')
        events = self.ui._gesture_mouse.call_args_list
        self.assertEqual(len(events),26)
        self.assertEqual(events[0].args,(2,0,0,1))
        self.assertEqual(events[12].args,(3,120,60,1))
        self.assertEqual(events[-1].args,(4,240,120,1))
        self.assertEqual(self.ui._modifier.call_args_list[-1].args,('cmd',0))

    def test_cancel_each_boundary_releases_owned_input(self):
        for boundary in range(1,29):
            with self.subTest(boundary=boundary):
                self.ui._gesture_mouse.reset_mock()
                self.ui._modifier.reset_mock()
                count = 0
                def check():
                    nonlocal count
                    count += 1
                    if count == boundary:
                        raise RuntimeError('cancel')
                try:
                    self.ui.drag(0,0,24,24,['cmd'],check)
                except RuntimeError:
                    pass
                kinds = [call.args[0] for call in self.ui._gesture_mouse.call_args_list]
                if 2 in kinds:
                    self.assertEqual(kinds.count(4),1)
                    self.assertEqual(kinds[-1],4)
                if self.ui._modifier.call_count:
                    self.assertEqual(self.ui._modifier.call_args.args,('cmd',0))

    def test_failed_mouse_post_still_releases(self):
        def post(kind,*args):
            if kind == 3:
                raise RuntimeError('post failure')
        self.ui._gesture_mouse.side_effect = post
        with self.assertRaises(RuntimeError):
            self.ui.drag(0,0,24,24,['cmd'])
        self.assertEqual(self.ui._gesture_mouse.call_args.args[0],4)
        self.assertEqual(self.ui._modifier.call_args.args,('cmd',0))

    def test_physical_input_is_not_released(self):
        self.q.CGEventSourceButtonState.return_value=True
        with self.assertRaises(RuntimeError):
            self.ui.drag(0,0,1,1)
        self.ui._gesture_mouse.assert_not_called()

    def test_scroll_directions_and_cancel_before_wheel(self):
        for direction,v,h in [('up',3,0),('down',-3,0),('left',0,3),('right',0,-3)]:
            self.ui.scroll(1,2,direction,3)
            self.assertEqual(self.q.CGEventCreateScrollWheelEvent.call_args.args[-2:],(v,h))
        self.q.CGEventCreateScrollWheelEvent.reset_mock()
        n=0
        def check():
            nonlocal n
            n+=1
            if n==2:
                raise RuntimeError('cancel')
        with self.assertRaises(RuntimeError):
            self.ui.scroll(1,2,'down',3,check)
        self.q.CGEventCreateScrollWheelEvent.assert_not_called()

    def test_key_cancellation_releases_posted_key(self):
        n=0
        def check():
            nonlocal n
            n+=1
            if n==2:
                raise RuntimeError('cancel')
        with self.assertRaises(RuntimeError):
            self.ui.key('cmd+return',check)
        self.assertEqual([c.args[-1] for c in self.q.CGEventCreateKeyboardEvent.call_args_list],[True,False])
