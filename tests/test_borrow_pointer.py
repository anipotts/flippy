"""Borrowing the pointer (flippy/mac/ui.py Platform._borrow_pointer) for apps that ignore background clicks:
only while the user is idle, only if the spot is that app's window, and the pointer and their app always go back."""
import ast
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from flippy.actions import RetryableActionError

ROOT = Path(__file__).resolve().parents[1]


def borrow_fn(namespace):
    tree = ast.parse((ROOT / "flippy/mac/ui.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Platform")
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_borrow_pointer")
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<borrow>", "exec"), namespace)
    return namespace["_borrow_pointer"]


class Borrow(unittest.TestCase):
    def setUp(self):
        self.idle = [5.0]
        now = [0.0]
        self.clock = SimpleNamespace(monotonic=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
        self.quartz = SimpleNamespace(
            kCGEventSourceStateHIDSystemState=1, kCGAnyInputEventType=2,
            CGEventSourceSecondsSinceLastEventType=lambda *a: self.idle[0],
            CGEventGetLocation=lambda ev: "home", CGEventCreate=lambda x: None,
            CGWarpMouseCursorPosition=Mock(), CGAssociateMouseAndMouseCursorPosition=Mock())
        self.target = SimpleNamespace(activateWithOptions_=Mock(), processIdentifier=lambda: 42)
        self.theirs = SimpleNamespace(activateWithOptions_=Mock(), processIdentifier=lambda: 7)
        self.front = [self.theirs]
        ws = SimpleNamespace(frontmostApplication=lambda: self.front[0])
        appkit = SimpleNamespace(NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: ws),
                                 NSApplicationActivateIgnoringOtherApps=1)
        ax = SimpleNamespace(running_app=lambda pid: self.target, _window=lambda pid: None, AX=SimpleNamespace())
        import flippy.mac as mac_pkg
        self._saved_ax = mac_pkg.__dict__.get("ax")  # the real flippy.mac.ax needs AppKit: never import it here
        self.ns = {"__name__": "flippy.mac.ui", "__package__": "flippy.mac", "Quartz": self.quartz, "AppKit": appkit,
                   "time": self.clock}
        mac_pkg.ax = ax  # the function imports `from . import ax`
        self.borrow = borrow_fn(self.ns)
        self.ui = SimpleNamespace(BORROW_IDLE_S=1.0, BORROW_WAIT_S=45.0, _window_owner_at=lambda x, y: 42)
        self.target.activateWithOptions_.side_effect = lambda o: self.front.__setitem__(0, self.target)

    def tearDown(self):
        import flippy.mac as mac_pkg
        if self._saved_ax is None:
            del mac_pkg.ax
        else:
            mac_pkg.ax = self._saved_ax

    def test_clicks_then_gives_the_pointer_and_their_app_back(self):
        act = Mock(return_value="ok")
        self.borrow(self.ui, 42, 10, 20, act, threading.Event())
        act.assert_called_once()
        self.quartz.CGWarpMouseCursorPosition.assert_called_once_with("home")
        self.theirs.activateWithOptions_.assert_called_once()

    def test_never_takes_it_while_they_keep_working(self):
        self.idle[0] = 0.2
        act = Mock()
        with self.assertRaises(RetryableActionError):
            self.borrow(self.ui, 42, 10, 20, act, threading.Event())
        act.assert_not_called()
        self.target.activateWithOptions_.assert_not_called()

    def test_refuses_when_something_else_covers_the_spot_and_still_restores(self):
        self.ui._window_owner_at = lambda x, y: 999
        act = Mock()
        with self.assertRaises(RetryableActionError):
            self.borrow(self.ui, 42, 10, 20, act, threading.Event())
        act.assert_not_called()
        self.quartz.CGWarpMouseCursorPosition.assert_called_once_with("home")
        self.theirs.activateWithOptions_.assert_called_once()


if __name__ == "__main__":
    unittest.main()
