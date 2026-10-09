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
        for message in ('one display required','Accessibility permission required'):
            with self.subTest(message=message):
                f=SimpleNamespace(busy=False,video=SimpleNamespace(recording=False),input_disabled=False,
                    ui=SimpleNamespace(action_state=Mock(),action_preflight=Mock(side_effect=ActionError(message))),
                    _begin_request=Mock(),brain=Mock(),box=Mock(),shooter=Mock())
                self.assertEqual(act(f,'click the fixture'),message)
                f._begin_request.assert_not_called()
                f.ui.action_state.assert_not_called()
                f.box.hide.assert_not_called()
                f.brain.act.assert_not_called()
                f.shooter.take.assert_not_called()

    def test_native_preflight_checks_displays_and_access_without_focus_or_prompt(self):
        q=SimpleNamespace(CGPreflightPostEventAccess=Mock(return_value=True),
                          CGRequestPostEventAccess=Mock())
        screens=SimpleNamespace(screens=Mock(return_value=[object(),object()]))
        namespace={'__name__':'flippy.mac.ui','__package__':'flippy.mac','Quartz':q,'NSScreen':screens}
        preflight=method(ROOT/'flippy/mac/ui.py','Platform','action_preflight',namespace)
        with self.assertRaisesRegex(ActionError,'one display'): preflight(SimpleNamespace())
        q.CGPreflightPostEventAccess.assert_not_called()
        screens.screens.return_value=[object()]
        q.CGPreflightPostEventAccess.return_value=False
        with self.assertRaisesRegex(ActionError,'Accessibility'): preflight(SimpleNamespace())
        q.CGRequestPostEventAccess.assert_not_called()
        q.CGPreflightPostEventAccess.return_value=True
        self.assertIsNone(preflight(SimpleNamespace()))
