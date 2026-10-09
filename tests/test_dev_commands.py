"""Controller command ownership and CLI validation, with no daemon or native UI."""
import ast
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flippy import settings

ROOT = Path(__file__).resolve().parents[1]


def make_controller():
    path = ROOT / 'flippy/daemon.py'
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Flippy')
    ns = {'__file__': str(path), 'os': os, 'json': json, 'settings': settings,
          'PROFILE': SimpleNamespace(name='demo',demo=True),
          'updates': SimpleNamespace(current_version=lambda: 'fixture'),
          'diagnostics': SimpleNamespace(command=Mock()),
          'demos': SimpleNamespace(dispatch=lambda *args: (False,None))}
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name in ('command','set_command'):
            exec(compile(ast.Module(body=[node],type_ignores=[]), '<controller commands>', 'exec'), ns)
    controller=type('Controller',(),{key:ns[key] for key in ('command','set_command')})()
    controller.busy=False
    controller.input_disabled=True
    controller.ui=SimpleNamespace(permission_state=lambda: {'accessibility':False,'screen_recording':False})
    controller.quit=Mock()
    return controller


class TestDevCommands(unittest.TestCase):
    def setUp(self):
        self.controller=make_controller()
        self.original=copy.deepcopy(settings._data)

    def tearDown(self):
        settings._data=self.original

    def test_doctor_reports_daemon_checkout_and_process(self):
        with patch.dict(os.environ, {'FLIPPY_APP':'/fixture/Flippy Demo.app'}):
            result=json.loads(self.controller.command('doctor'))
        self.assertEqual(result['root'],os.path.realpath(ROOT))
        self.assertEqual(result['pid'],os.getpid())
        self.assertEqual(result['app'],'/fixture/Flippy Demo.app')
        self.assertEqual(result['profile'],'demo')
        self.assertTrue(result['input_disabled'])
        self.assertEqual(result['permissions'], {'accessibility':False,'screen_recording':False})
        self.assertEqual(set(result),{'root','pid','app','profile','version','busy','input_disabled','permissions','last_action'})
        self.assertIsNone(result['last_action'])

    def test_owned_quit_accepts_canonical_equivalent_checkout(self):
        spelling=str(ROOT / 'flippy' / '..')
        self.assertEqual(self.controller.command('quit-owned '+spelling),'ok')
        self.controller.quit.assert_called_once()

    def test_foreign_quit_is_refused_without_teardown(self):
        result=self.controller.command('quit-owned /fixture/another-checkout')
        self.assertTrue(result.startswith('refused:'))
        self.controller.quit.assert_not_called()

    def test_settings_cli_refuses_fractional_integer_bad_bool_and_nonfinite(self):
        cases=('look.text_size 12.5','timing.show_seconds 4.2',
               'automation.clicks definitely','automation.clicks 0.5',
               'timing.speed nan','timing.speed inf','timing.speed -inf')
        with patch.object(settings,'_save') as save:
            for command in cases:
                with self.subTest(command=command):
                    self.assertNotEqual(self.controller.set_command(command),'ok')
            save.assert_not_called()
        self.assertEqual(settings._data,self.original)

    def test_settings_save_failure_keeps_memory_and_reports_error(self):
        initial=settings.get('timing','speed')
        value=1.5 if initial != 1.5 else 1.0
        with patch.object(settings,'_save',side_effect=OSError('fixture')):
            result=self.controller.set_command(f'timing.speed {value}')
        self.assertNotEqual(result,'ok')
        self.assertEqual(settings.get('timing','speed'),initial)
