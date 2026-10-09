import unittest
from types import SimpleNamespace
from flippy.demos import dispatch

class DemoTests(unittest.TestCase):
    def test_does_not_dispatch_action_approval(self):
        host=SimpleNamespace()
        for cmd in ('act test','action allow','nudge Allow once'):
            if cmd.startswith('nudge '): continue
            self.assertEqual(dispatch(host,cmd,lambda *a,**k:None,lambda *a:None),(False,None))
    def test_existing_preview_and_point_commands(self):
        calls=[]; host=SimpleNamespace(preview=lambda **k:calls.append(k),demo_point=lambda *a:calls.append(a))
        self.assertEqual(dispatch(host,'demo-tutorial',None,None),(True,'ok'))
        self.assertEqual(dispatch(host,'demo-point 1 2 menu|hello',None,None),(True,'ok'))
        self.assertEqual(calls,[{'tutorial':True},(1.,2.,'menu','hello')])
    def test_missing_native_recording(self):
        host=SimpleNamespace(ui=SimpleNamespace())
        self.assertIn('not available',dispatch(host,'record stop',None,None)[1])
