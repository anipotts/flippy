"""Approval scope cannot grant sensitive apps, and tool budgets remain bounded."""
import asyncio
import unittest

from flippy.actions import ApprovalPolicy, DesktopTools, TOOL_CATALOG, app_id
from flippy.frames import ScreenFrame


def target(app='dev.flippy.fixture',pid=123):
    return app,pid,7,(0,0,200,200),(1,(200,200))


class TestPolicy(unittest.TestCase):
    def test_per_app_grants_one_instance_and_remembers_explicit_app_ids(self):
        policy=ApprovalPolicy()
        self.assertTrue(policy.needs_approval(target()))
        policy.grant(target())
        self.assertFalse(policy.needs_approval(target()))
        self.assertTrue(policy.needs_approval(target(pid=124)))
        self.assertFalse(policy.needs_approval(target(pid=124),remembered=['DEV.FLIPPY.FIXTURE']))
        self.assertTrue(ApprovalPolicy().needs_approval(target()))

    def test_sensitive_apps_and_browsers_always_require_each_input(self):
        apps=('com.apple.systempreferences','com.apple.keychainaccess','com.apple.Terminal',
              'com.googlecode.iterm2','com.1password.1password','com.bitwarden.desktop',
              'com.apple.Safari','com.google.Chrome','org.mozilla.firefoxdeveloperedition',
              'company.thebrowser.Browser','com.example.PasswordVault')
        for mode in ApprovalPolicy.MODES:
            for app in apps:
                with self.subTest(mode=mode,app=app):
                    policy=ApprovalPolicy(mode)
                    policy.grant(target(app))
                    self.assertTrue(policy.sensitive(target(app)))
                    self.assertTrue(policy.needs_approval(target(app),remembered=[app.lower()]))

    def test_auto_only_bypasses_known_native_identifier_and_every_input_never_bypasses(self):
        self.assertFalse(ApprovalPolicy('auto').needs_approval(target()))
        every=ApprovalPolicy('every_input')
        every.grant(target())
        self.assertTrue(every.needs_approval(target(),remembered=['dev.flippy.fixture']))
        for unknown in (None,(),('Terminal',123),('dev.flippy.fixture',None),('dev.flippy.fixture',True)):
            with self.subTest(target=unknown):
                self.assertIsNone(app_id(unknown))
                for mode in ApprovalPolicy.MODES:
                    policy=ApprovalPolicy(mode); policy.grant(unknown)
                    self.assertTrue(policy.needs_approval(unknown))

    def test_invalid_mode_and_limits_rejected(self):
        with self.assertRaises(ValueError): ApprovalPolicy('unbounded')
        for kwargs in ({'max_actions':0},{'max_actions':41},{'max_actions':True},
                       {'max_text':2001},{'max_text':False},{'approval_mode':'unbounded'}):
            with self.assertRaises(ValueError): DesktopTools(None,None,None,**kwargs)


class TestToolBudgets(unittest.IsolatedAsyncioTestCase):
    async def test_expanded_text_schema_validation_and_per_app_review_are_consistent(self):
        inputs=[]
        async def capture(): return ScreenFrame('jpeg',(200,200),(200,200),target())
        async def approve(*args): return True
        async def perform(name,args,*rest): inputs.append((name,args))
        tools=DesktopTools(capture,approve,perform,max_actions=2,max_text=2000,approval_mode='per_app')
        self.assertEqual(tools.catalog()['type']['schema']['properties']['text']['maxLength'],2000)
        self.assertEqual(TOOL_CATALOG['type']['schema']['properties']['text']['maxLength'],160)
        await tools.invoke('screenshot',{})
        result=await tools.invoke('type',{'text':'x'*2000,'reason':'fill fixture'})
        self.assertNotIn('is_error',result)
        self.assertEqual(len(inputs[0][1]['text']),2000)
        self.assertNotIn('is_error',await tools.invoke('key',{'combo':'cmd+o','reason':'open'}))
        self.assertTrue((await tools.invoke('key',{'combo':'cmd+space','reason':'search'}))['is_error'])
        self.assertEqual(len(inputs),2)

    async def test_sensitive_long_input_is_refused_before_approval(self):
        approvals=[]
        async def capture(): return ScreenFrame('jpeg',(200,200),(200,200),target('com.apple.Safari'))
        async def approve(*args): approvals.append(args); return True
        async def perform(*args): raise AssertionError('must not perform')
        tools=DesktopTools(capture,approve,perform,max_text=2000,approval_mode='auto')
        await tools.invoke('screenshot',{})
        self.assertTrue((await tools.invoke('type',{'text':'x'*2000,'reason':'write'}))['is_error'])
        self.assertEqual(approvals,[])

    async def test_drag_window_bounds_are_enforced_before_auto_approval(self):
        approvals=[]
        async def capture():
            return ScreenFrame('jpeg',(200,200),(200,200),('dev.flippy.fixture',123,7,(20,20,60,60),(1,(200,200))))
        async def approve(*args): approvals.append(args); return True
        async def perform(*args): raise AssertionError('must not perform')
        tools=DesktopTools(capture,approve,perform,approval_mode='auto')
        await tools.invoke('screenshot',{})
        result=await tools.invoke('drag',{'x':30,'y':30,'to_x':120,'to_y':120,'modifiers':[],'reason':'move'})
        self.assertTrue(result['is_error'])
        self.assertEqual(approvals,[])
