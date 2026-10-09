"""Eligibility is checked before request ownership, capture or model inference."""
import ast
import os
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

    def test_target_requires_window_geometry_and_tracks_display_identity(self):
        screen=SimpleNamespace(deviceDescription=Mock(return_value={'NSScreenNumber':11}))
        sensors=SimpleNamespace(frontmost=lambda: ('fixture','Fixture',123456),
            front_window=Mock(return_value=7), windows=Mock(return_value=[(7,(20,20,80,80))]))
        namespace={'__name__':'flippy.mac.ui','__package__':'flippy.mac','os':os,
            'NSScreen':SimpleNamespace(screens=lambda: [screen]),'sensors':sensors}
        state=method(ROOT/'flippy/mac/ui.py','Platform','action_state',namespace)
        ui=SimpleNamespace(screen_size=lambda: (100,100))
        original=state(ui)
        self.assertEqual(original,('fixture',123456,7,(20,20,80,80),(11,(100,100))))
        screen.deviceDescription.return_value={'NSScreenNumber':12}
        replacement=state(ui)
        self.assertNotEqual(original[-1],replacement[-1])
        sensors.front_window.return_value=None
        with self.assertRaisesRegex(ActionError,'foreground window'): state(ui)
        sensors.front_window.return_value=7
        sensors.windows.return_value=[]
        with self.assertRaisesRegex(ActionError,'foreground window'): state(ui)
