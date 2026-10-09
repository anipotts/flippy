"""Native setup regressions, with no authentication, input, or settings writes."""
import contextlib
import os
import sys
import tempfile
import unittest
from unittest import mock

if sys.platform == 'darwin':
    from AppKit import NSApplication, NSImageView
    from Foundation import NSMakeRect
    from flippy.mac import setup_window as setup, setup_style as style
    from flippy.mac.permission_buddy import PermissionBuddy


@unittest.skipUnless(sys.platform == 'darwin', 'native AppKit setup')
class TestSetupRedesign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = NSApplication.sharedApplication()

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.app_path = os.path.join(self.directory, 'Flippy.app')
        os.mkdir(self.app_path)
        self.stack.enter_context(mock.patch.object(setup, 'APP', self.app_path))
        self.stack.enter_context(mock.patch.object(setup, 'current', return_value=mock.Mock(demo=False)))
        self.stack.enter_context(mock.patch.object(setup, 'login_item_on', return_value=False))
        self.screen_ok = self.stack.enter_context(mock.patch.object(setup, 'screen_ok', return_value=False))
        self.access_ok = self.stack.enter_context(mock.patch.object(setup.hotkeys, 'accessibility_trusted', return_value=False))
        self.timer = self.stack.enter_context(mock.patch.object(setup.loop, 'timeout_add', return_value=713))
        self.remove_timer = self.stack.enter_context(mock.patch.object(setup.loop, 'source_remove'))
        self.state = {'claude': True, 'codex': True}
        from flippy import providers
        self.stack.enter_context(mock.patch.object(providers, 'CONNECTION_STATUS', self.state))
        original_get = setup.settings.get
        self.values = {('provider', 'mode'): 'auto', ('keys', 'ask'): 'shift+cmd+space'}
        self.stack.enter_context(mock.patch.object(setup.settings, 'get', side_effect=lambda group, key: self.values.get((group, key), original_get(group, key))))
        self.write = self.stack.enter_context(mock.patch.object(setup.settings, 'set', side_effect=lambda group, key, value: self.values.__setitem__((group, key), value)))
        self.open_settings, self.closed = mock.Mock(), mock.Mock()
        self.window = None
        self.addCleanup(self.close_window)

    def close_window(self):
        if self.window is not None:
            self.window.win.close()

    def build(self):
        self.window = setup.SetupWindow(self.open_settings, self.closed)
        return self.window

    def click(self, control):
        control.target().fire_(control)

    def descendants(self, view):
        for child in view.subviews():
            yield child
            yield from self.descendants(child)

    def test_provider_choice_is_one_validated_write_and_login_is_not_inference(self):
        window = self.build()
        popup = window.provider_choice
        popup.selectItemAtIndex_(popup.target().values.index('codex'))
        self.click(popup)
        self.write.assert_called_once_with('provider', 'mode', 'codex')
        self.assertIn('not ready', window.marks['codex'].stringValue())
        self.assertIn('Login found', window.marks['codex'].stringValue())
        self.state['codex'] = False
        window._refresh()
        self.assertIn('not ready', window.marks['codex'].stringValue())
        self.assertNotIn('Login found', window.marks['codex'].stringValue())

    def test_live_permission_marks_update_accessible_status(self):
        window = self.build()
        self.assertIn('not enabled', window.marks['screen'].accessibilityLabel())
        self.assertIn('not enabled', window.marks['accessibility'].accessibilityLabel())
        self.screen_ok.return_value = self.access_ok.return_value = True
        window._refresh()
        self.assertEqual(window.marks['screen'].accessibilityLabel(), 'screen permission enabled')
        self.assertEqual(window.marks['accessibility'].accessibilityLabel(), 'accessibility permission enabled')

    def test_permission_buttons_open_correct_panes_only_on_user_action(self):
        with mock.patch.object(setup.subprocess, 'Popen') as launch, mock.patch.object(setup, 'CGRequestScreenCaptureAccess') as request:
            window = self.build()
            launch.assert_not_called()
            request.assert_not_called()
            self.click(window.screen_button)
            request.assert_called_once_with()
            launch.assert_called_with(['open', setup.SCREEN_PANE])
            self.click(window.accessibility_button)
            launch.assert_called_with(['open', setup.ACCESSIBILITY_PANE])

    def test_buddy_and_finder_use_exact_installed_app(self):
        window = self.build()
        buddies = [view for view in self.descendants(window.body) if isinstance(view, PermissionBuddy)]
        self.assertGreaterEqual(len(buddies), 1)
        for buddy in buddies:
            self.assertEqual(buddy.app_path, os.path.abspath(self.app_path))
            self.assertIsNotNone(buddy.image())
        with mock.patch.object(setup, 'reveal_app') as reveal:
            self.click(window.finder_button)
            reveal.assert_called_once_with(self.app_path)

    def test_shortcut_keycaps_follow_live_setting_and_modifier_order(self):
        window = self.build()
        def caps():
            return [view.stringValue() for view in self.descendants(window.shortcut_view) if hasattr(view, 'stringValue')]
        self.assertEqual(caps(), ['⇧', '⌘', 'Space'])
        self.values['keys', 'ask'] = 'cmd+ctrl+option+k'
        window._refresh()
        self.assertEqual(caps(), ['⌃', '⌥', '⌘', 'K'])
        self.assertIn('K', window.shortcut_view.accessibilityLabel())
        self.assertEqual(style.shortcut_tokens('double-cmd'), ['⌘', '⌘'])

    def test_keyboard_controls_have_complete_cycle_and_done_is_default(self):
        window = self.build()
        for index, control in enumerate(window.controls):
            self.assertEqual(control.nextKeyView(), window.controls[(index + 1) % len(window.controls)])
        self.assertEqual(window.done_button.keyEquivalent(), '\r')
        self.assertEqual(window.provider_buttons['claude'].keyEquivalent(), '')
        self.click(window.edit_button)
        self.open_settings.assert_called_once_with()

    def test_small_display_keeps_footer_and_controls_in_their_containers(self):
        screen = mock.Mock()
        screen.visibleFrame.return_value = NSMakeRect(0, 0, 1024, 600)
        with mock.patch.object(setup, 'NSScreen') as screens:
            screens.mainScreen.return_value = screen
            window = self.build()
        self.assertLess(window.win.frame().size.height, 600)
        self.assertTrue(window.scroll.hasVerticalScroller())
        self.assertEqual(window.done_button.superview(), window.win.contentView())
        for control in window.controls:
            frame, parent = control.frame(), control.superview().bounds()
            self.assertGreaterEqual(frame.origin.x, 0)
            self.assertGreaterEqual(frame.origin.y, 0)
            self.assertLessEqual(frame.origin.x + frame.size.width, parent.size.width)
            self.assertLessEqual(frame.origin.y + frame.size.height, parent.size.height)

    def test_provider_assets_are_decodable_native_images(self):
        window = self.build()
        logos = [view for view in self.descendants(window.body) if isinstance(view, NSImageView) and (view.accessibilityLabel() or '').endswith(' logo')]
        self.assertEqual(len(logos), 2)
        for logo in logos:
            self.assertIsNotNone(logo.image())
            self.assertGreater(logo.image().size().width, 0)

    def test_demo_cannot_enable_login_item_and_close_removes_poll(self):
        with mock.patch.object(setup, 'current', return_value=mock.Mock(demo=True)), mock.patch.object(setup, 'set_login_item') as login:
            window = self.build()
            self.assertFalse(window.login_switch.isEnabled())
            login.assert_not_called()
        window.win.close()
        self.window = None
        self.remove_timer.assert_called_once_with(713)
        self.closed.assert_called_once_with()
        self.timer.assert_called_once()


if __name__ == '__main__':
    unittest.main()
