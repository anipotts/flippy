"""Eligibility is checked before request ownership, capture or model inference."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from flippy.actions import ActionError

ROOT = Path(__file__).resolve().parents[1]


def method(path, owner, name, namespace):
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner)
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<preflight>', 'exec'), namespace)
    return namespace[name]


class TestActionEligibility(unittest.TestCase):
    def test_refusal_starts_no_request_capture_or_model(self):
        act = method(ROOT/'flippy/daemon.py','Flippy','act',{'ActionError':ActionError})
        message = 'Accessibility permission required'
        f=SimpleNamespace(busy=False,video=SimpleNamespace(recording=False),input_disabled=False,
            ui=SimpleNamespace(app_look=Mock(),app_front=Mock(),app_preflight=Mock(side_effect=ActionError(message))),
            _begin_request=Mock(),brain=Mock(),box=Mock(),shooter=Mock())
        self.assertEqual(act(f,'click the fixture'),message)
        f._begin_request.assert_not_called()
        f.ui.app_front.assert_not_called()
        f.ui.app_look.assert_not_called()
        f.box.hide.assert_not_called()
        f.brain.act.assert_not_called()
        f.shooter.take.assert_not_called()
