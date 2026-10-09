"""First-run setup on macOS: Claude login, Screen Recording, hotkeys, open at login.

Shown automatically until every required step is done (and from the menu bar's
"Setup…"). Each step's status is re-checked every second, so granting a
permission in System Settings ticks it off here without any clicking.
"""
import os
import plistlib
import subprocess

from AppKit import (NSApp, NSBackingStoreBuffered, NSColor, NSWindow, NSWindowStyleMaskClosable,
                    NSWindowStyleMaskTitled)
from Foundation import NSMakeRect, NSObject
from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess

from .. import loop, settings
from ..profile import current
from . import hotkeys
from .widgets import Form, button, checkbox, label, popup

APP = os.environ.get("FLIPPY_APP")  # set by Flippy.app's launcher; None when run from a terminal
AGENT_LABEL = current().bundle_id
AGENT = os.path.expanduser(f"~/Library/LaunchAgents/{AGENT_LABEL}.plist")
SCREEN_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
WIDTH = 560


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
    cli = shutil.which("codex")
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
        self.keep = []
        self.marks = {}
        f = Form(WIDTH)
        self.keep.append(f)
        f.group("Welcome to Flippy", "Ask about anything on your screen and Flippy points at it. "
                                     "Two quick steps and you're set.")

        f.y += 6
        f.row("1. Connect your subscription", "Use Claude Code or Codex / ChatGPT. If both are connected, choose one below.",
              button("Log in…", open_login_terminal, self.keep), mark=self._mark("claude"))
        f.row("ChatGPT via Codex", "API-key connections are refused. Included-only credit enforcement is still under verification.",
              button("Sign in…", open_codex_login, self.keep), mark=self._mark("codex"))
        f.row("Use", "Auto selects the only connected subscription. Changing provider starts a fresh conversation.",
              popup(settings.options("provider", "mode"), settings.get("provider", "mode"),
                    lambda value: settings.set("provider", "mode", value), self.keep))
        f.y += 6
        f.row("2. Allow screen recording", "Flippy sends a screenshot with each question so Claude can see what "
                                           "you mean. macOS applies it after Flippy restarts.",
              button("Allow…", ask_screen, self.keep), mark=self._mark("screen"))
        f.buttons(button("Restart Flippy", restart, self.keep))

        f.group("Hotkeys")
        ask, draw, video = (hotkeys.pretty(settings.get("keys", k)) for k in ("ask", "draw", "video"))
        f.row(f"{ask}   Ask about the screen", f"{draw}   Circle something, then ask\n{video}   Check a video edit",
              button("Change…", open_settings, self.keep))

        f.group("Options")
        login = checkbox("Open Flippy at login", login_item_on(), set_login_item, self.keep)
        login.setEnabled_(bool(APP))
        f.add(login)
        if not APP:
            f.add(label("Available once Flippy is installed as an app (./install.sh).", 11,
                        color=NSColor.secondaryLabelColor()))
        f.y += 4
        f.buttons(button("Done", lambda: self.win.close(), self.keep, primary=True))

        view = f.finish()
        h = view.frame().size.height
        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, h), NSWindowStyleMaskTitled | NSWindowStyleMaskClosable, NSBackingStoreBuffered, False)
        self.win.setTitle_("Set up Flippy")
        self.win.setReleasedWhenClosed_(False)
        self.win.setContentView_(view)
        self.win.center()
        self.delegate = _Delegate.alloc().init()

        def closed():
            loop.source_remove(self.poll_id)
            on_close()
        self.delegate.on_close = closed
        self.win.setDelegate_(self.delegate)
        self._refresh()
        self.poll_id = loop.timeout_add(1000, lambda: self._refresh() or True)

    def _mark(self, key):
        mark = label("○", 17)
        mark.setFrameSize_((22, 22))
        self.marks[key] = mark
        return mark

    def _refresh(self):
        from ..providers import CONNECTION_STATUS
        for key, ok in (("claude", claude_logged_in()), ("codex", CONNECTION_STATUS["codex"] is True), ("screen", screen_ok())):
            mark = self.marks[key]
            mark.setStringValue_("✓" if ok else "○")
            mark.setTextColor_(NSColor.systemGreenColor() if ok else NSColor.tertiaryLabelColor())

    def present(self):
        NSApp.activateIgnoringOtherApps_(True)
        self.win.makeKeyAndOrderFront_(None)
