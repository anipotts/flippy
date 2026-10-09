"""First-run setup on macOS: Claude login, Screen Recording, hotkeys, open at login.

Shown automatically until every required step is done (and from the menu bar's
"Setup…"). Each step's status is re-checked every second, so granting a
permission in System Settings ticks it off here without any clicking.
"""
import os
import plistlib
import subprocess

from AppKit import (NSApp, NSAppearance, NSBackingStoreBuffered, NSColor, NSImage, NSImageView,
                    NSScreen, NSScrollView, NSWindow, NSWindowStyleMaskClosable,
                    NSWindowStyleMaskTitled, NSImageScaleProportionallyUpOrDown, NSControlSizeSmall, NSSwitch)
from Foundation import NSMakeRect, NSObject
from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess

from .. import loop, settings
from ..profile import current
from . import hotkeys
from .permission_buddy import app_icon, reveal_app
from .widgets import popup, target
from . import setup_style as style

APP = os.environ.get("FLIPPY_APP")  # set by Flippy.app's launcher; None when run from a terminal
AGENT_LABEL = current().bundle_id
AGENT = os.path.expanduser(f"~/Library/LaunchAgents/{AGENT_LABEL}.plist")
SCREEN_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
ACCESSIBILITY_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
WIDTH = 560
BODY_HEIGHT = 674
FOOTER_HEIGHT = 52


# ---- checks
def claude_logged_in():
    from ..providers import CONNECTION_STATUS
    return CONNECTION_STATUS["claude"] is True


def screen_ok():
    return bool(CGPreflightScreenCaptureAccess())


def needs_setup():
    from ..providers import setup_ready
    return not (setup_ready() and screen_ok())


def claude_cli():
    """The CLI the Agent SDK uses: its bundled copy, else `claude` on PATH."""
    import claude_agent_sdk
    bundled = os.path.join(os.path.dirname(claude_agent_sdk.__file__), "_bundled", "claude")
    return bundled if os.path.exists(bundled) else "claude"


# ---- actions
def open_login_terminal():
    """Run `claude` in Terminal so the user can /login with their Pro/Max account."""
    cmd = f"unset ANTHROPIC_API_KEY; '{claude_cli()}'"
    script = f'tell application "Terminal" to do script "{cmd}"\ntell application "Terminal" to activate'
    subprocess.Popen(["osascript", "-e", script])


def open_codex_login():
    # The owner completes Codex's native browser flow; Flippy never handles tokens.
    import shutil
    import shlex
    from ..codex_provider import codex_executable
    cli = codex_executable()  # not only PATH: apps get a minimal one
    if not cli:
        subprocess.Popen(["open", "https://developers.openai.com/codex/cli/"])
        return
    command = "unset OPENAI_API_KEY CODEX_API_KEY; " + shlex.quote(cli) + " -c 'forced_login_method=\"chatgpt\"' login"
    script = 'tell application "Terminal" to do script ' + __import__('json').dumps(command)
    subprocess.Popen(["osascript", "-e", script])


def ask_screen():
    CGRequestScreenCaptureAccess()  # the system prompt (only the first time)
    subprocess.Popen(["open", SCREEN_PANE])


def restart():
    """macOS applies Screen Recording only to newly started processes."""
    from . import ui
    ui.PLATFORM.restart()


def login_item_on():
    if current().demo:
        return False
    return os.path.exists(AGENT)


def set_login_item(on):
    """A LaunchAgent that opens Flippy.app at login (no extra permission needed)."""
    if current().demo:
        return  # the development profile never installs or removes login items
    if not on:
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{AGENT_LABEL}"], capture_output=True)
        try:
            os.unlink(AGENT)
        except FileNotFoundError:
            pass
        return
    if not APP:
        return
    os.makedirs(os.path.dirname(AGENT), exist_ok=True)
    with open(AGENT, "wb") as f:
        plistlib.dump({"Label": AGENT_LABEL, "ProgramArguments": ["/usr/bin/open", "-g", APP], "RunAtLoad": True}, f)


# ---- window
class _Delegate(NSObject):
    def windowWillClose_(self, note):
        self.on_close()


class SetupWindow:
    def __init__(self, open_settings, on_close):
        self.keep, self.marks, self.provider_buttons = [], {}, {}
        self.open_settings = open_settings
        self.body = style.panel(WIDTH, BODY_HEIGHT)
        self.body.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
        b = self.body
        installed = bool(APP and os.path.isdir(APP))
        style.place(b, style.flippy_mark(60), 20, 16, 60, 60)
        style.text(b, "Hi, I'm Flippy.", 96, 22, 420, 25, bold=True)
        style.text(b, "Ask about anything on your screen. I'll point it out.", 96, 55, 420, 12, muted=True)
        style.rule(b, 88, WIDTH - 48)

        style.section(b, 1, "Connect", "Use the subscription you've already got.", 100, WIDTH)
        self._provider_card("claude", "Claude", "Via Claude Code", "claude.png", 24, 142,
                            "Connect", open_login_terminal)
        self._provider_card("codex", "ChatGPT", "Via Codex · not ready yet", "openai.png", 286, 142,
                            "Sign in…", open_codex_login)
        style.text(b, "Use", 24, 222, 130, 12, bold=True)
        style.text(b, "Auto picks the only connected subscription.", 24, 240, 265, 10, muted=True)
        self.provider_choice = popup(settings.options("provider", "mode"), settings.get("provider", "mode"),
                                     self._choose_provider, self.keep, width=230)
        style.outline_popup(self.provider_choice)
        self.provider_choice.setAccessibilityLabel_("Subscription to use")
        style.place(b, self.provider_choice, 306, 221, 230, 28)
        style.text(b, "ChatGPT isn't ready yet. Runtime and subscription-only usage checks are still pending.",
                   24, 265, WIDTH - 48, 10, muted=True)
        style.rule(b, 294, WIDTH - 48)

        style.section(b, 2, "Permissions", "Let me see your screen and lend a hand.", 306, WIDTH)
        card = style.card(WIDTH - 48, 62)
        style.place(b, card, 24, 348)
        if installed:
            buddy = app_icon(APP)  # still drags the real app into Settings; only its look matches the setup
            buddy.setImage_(style.flippy_mark(48).image())
            buddy.setImageScaling_(NSImageScaleProportionallyUpOrDown)
            style.place(card, buddy, 8, 7, 48, 48)
            style.text(card, os.path.basename(APP), 66, 12, 235, 12, bold=True)
            home = os.path.expanduser("~")
            path = os.path.abspath(APP)
            display_path = "~" + path[len(home):] if path.startswith(home + os.sep) else path
            path_label = style.text(card, display_path, 66, 32, 235, 10, muted=True)
            path_label.setToolTip_(path)
            self.finder_button = style.button("Show in Finder", lambda: reveal_app(APP), self.keep)
            style.place(card, self.finder_button, 368, 18, 132, 26)
            card.setToolTip_("Drag this Flippy icon into Settings, or choose this exact app with +.")
        else:
            style.text(card, "Run the installed Flippy.app to drag it into Settings.", 16, 21, 470, 12)
        self._permission_row("screen", "display", "Screen Recording",
                             "So I can see what you're asking about.", 422, ask_screen)
        self._permission_row("accessibility", "accessibility", "Accessibility",
                             "For desktop actions and double-tap shortcuts.", 468,
                             lambda: subprocess.Popen(["open", ACCESSIBILITY_PANE]))
        style.text(b, "Drag the icon into Settings. If dropping won't work, use + or Show in Finder.",
                   24, 515, WIDTH - 48, 10, muted=True)
        style.rule(b, 536, WIDTH - 48)
        style.text(b, "Restart Flippy after enabling permissions.", 24, 550, 360, 11, muted=True)
        self.restart_button = style.button("Restart", restart, self.keep)
        style.place(b, self.restart_button, 454, 542, 82, 28)
        style.rule(b, 581, WIDTH - 48)

        style.section(b, 3, "Your shortcut", "That's how you call me, from any app.", 593, WIDTH)
        self.shortcut_view = style.panel(320, 32)
        style.place(b, self.shortcut_view, 62, 635)
        self._shortcut = None
        self.edit_button = style.button("Edit…", open_settings, self.keep)
        style.place(b, self.edit_button, 454, 635, 82, 28)
        self.edit_button.setAccessibilityLabel_("Edit Flippy shortcuts")

        # The footer stays visible; the body scrolls only on smaller displays.
        screen_height = NSScreen.mainScreen().visibleFrame().size.height
        content_height = min(BODY_HEIGHT + FOOTER_HEIGHT + 40, max(360, screen_height - 64))
        root = style.panel(WIDTH, content_height)
        root.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
        body_height = content_height - FOOTER_HEIGHT - 40
        self.scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, body_height))
        self.scroll.setDrawsBackground_(False)
        self.scroll.setHasVerticalScroller_(body_height < BODY_HEIGHT)
        self.scroll.setAutohidesScrollers_(True)
        self.scroll.setDocumentView_(b)
        style.place(root, self.scroll, 0, 0)
        style.rule(root, body_height, WIDTH - 48)
        self.login_switch = NSSwitch.alloc().initWithFrame_(NSMakeRect(24, body_height + 9, 36, 24))
        login_target = target(lambda sender: set_login_item(bool(sender.state())))
        self.keep.append(login_target)
        self.login_switch.setTarget_(login_target)
        self.login_switch.setAction_("fire:")
        self.login_switch.setControlSize_(NSControlSizeSmall)
        self.login_switch.setState_(int(login_item_on()))
        self.login_switch.setEnabled_(installed and not current().demo)
        self.login_switch.setAccessibilityLabel_("Launch Flippy at login")
        self.login_switch.sizeToFit()
        switch_w = self.login_switch.frame().size.width
        style.place(root, self.login_switch, WIDTH - 24 - switch_w + 5, body_height + 9)  # its pill ends at the buttons' edge
        style.text(root, "Launch at login", 24, body_height + 13, 240, 11)
        style.rule(root, body_height + 40, WIDTH, x=0)
        style.text(root, "You stay in control.", 24, body_height + 58, 360, 11, muted=True)
        self.done_button = style.button("Done", lambda: self.win.close(), self.keep, primary=True)
        style.place(root, self.done_button, 454, body_height + 49, 82, 28)
        self.controls = [self.provider_buttons['claude'], self.provider_buttons['codex'], self.provider_choice]
        if installed:
            self.controls.append(self.finder_button)
        self.controls += [self.screen_button, self.accessibility_button, self.restart_button,
                          self.edit_button, self.login_switch, self.done_button]
        for control, following in zip(self.controls, self.controls[1:] + self.controls[:1]):
            control.setNextKeyView_(following)

        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, content_height),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable, NSBackingStoreBuffered, False)
        self.win.setTitle_("Flippy")
        self.win.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
        self.win.setBackgroundColor_(style.color(style.BACKGROUND))
        self.win.setReleasedWhenClosed_(False)
        self.win.setContentView_(root)
        self.win.setInitialFirstResponder_(self.provider_buttons['claude'])
        self.win.center()
        self.delegate = _Delegate.alloc().init()

        def closed():
            loop.source_remove(self.poll_id)
            on_close()
        self.delegate.on_close = closed
        self.win.setDelegate_(self.delegate)
        self._refresh()
        self.poll_id = loop.timeout_add(1000, lambda: self._refresh() or True)

    def _provider_card(self, key, title, subtitle, asset, x, y, caption, callback):
        card = style.card(250, 66)
        style.place(self.body, card, x, y)
        image = NSImage.alloc().initWithContentsOfFile_(os.path.join(os.path.dirname(__file__), "assets", asset))
        logo = NSImageView.alloc().initWithFrame_(NSMakeRect(14, 20, 30, 30))
        logo.setImage_(image)
        logo.setAccessibilityLabel_(title + " logo")
        style.place(card, logo, 14, 18)
        style.text(card, title, 54, 13, 106, 12, bold=True)
        self.marks[key] = style.text(card, subtitle, 54, 32, 114, 10, muted=True)
        action = style.button(caption, callback, self.keep, primary=key == "claude")
        if key == "claude":
            action.setKeyEquivalent_("")
        action.setAccessibilityLabel_("Connect " + title)
        style.place(card, action, 172, 20, 68, 26)
        self.provider_buttons[key] = action

    def _permission_row(self, key, icon_name, title, subtitle, y, callback):
        mark = style.symbol("circle", title + " permission not enabled", 15)
        style.place(self.body, mark, 24, y + 10)
        self.marks[key] = mark
        style.place(self.body, style.symbol(icon_name, title), 55, y + 7, 24, 24)
        style.text(self.body, title, 94, y, 290, 12, bold=True)
        style.text(self.body, subtitle, 94, y + 19, 300, 10, muted=True)
        action = style.button("Open Settings", callback, self.keep)
        action.setAccessibilityLabel_("Open " + title + " settings")
        style.place(self.body, action, 432, y + 5, 104, 26)
        setattr(self, key + "_button", action)

    def _choose_provider(self, value):
        settings.set("provider", "mode", value)
        self._refresh()

    def _refresh(self):
        from ..providers import CONNECTION_STATUS
        claude = claude_logged_in()
        codex = CONNECTION_STATUS["codex"] is True
        self.marks['claude'].setStringValue_("Connected" if claude else "Via Claude Code")
        self.marks['codex'].setStringValue_("Login found · not ready" if codex else "Via Codex · not ready yet")
        self.provider_buttons['claude'].setTitle_("Log in…" if claude else "Connect")
        for key, ok in (("screen", screen_ok()), ("accessibility", hotkeys.accessibility_trusted())):
            mark = self.marks[key]
            mark.setImage_(NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "checkmark.circle.fill" if ok else "circle", key + (" enabled" if ok else " not enabled")))
            mark.setContentTintColor_(NSColor.systemGreenColor() if ok else style.color(style.MUTED))
            mark.setAccessibilityLabel_(key.replace('_', ' ') + (" permission enabled" if ok else " permission not enabled"))
        self.provider_choice.selectItemAtIndex_(
            self.provider_choice.target().values.index(settings.get("provider", "mode")))
        combo = settings.get('keys', 'ask')
        if combo != self._shortcut:
            for view in list(self.shortcut_view.subviews()):
                view.removeFromSuperview()
            style.keycaps(self.shortcut_view, combo, 0, 0)
            self.shortcut_view.setAccessibilityLabel_('Ask about the screen: ' + hotkeys.pretty(combo))
            self._shortcut = combo

    def present(self):
        NSApp.activateIgnoringOtherApps_(True)
        self.win.makeKeyAndOrderFront_(None)
