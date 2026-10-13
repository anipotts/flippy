"""First-run setup on macOS, for the app window's Setup page: Claude and Codex sign-in, Screen Recording,
Accessibility, open at login, restart. The page (flippy/shell/web/setup.js) shows state() and asks for act(name).

The page is shown by itself until every required step is done (flippy/setup_gate.py) and from the menu bar's
"Setup…". It re-reads state() every second while it's showing, so granting a permission in System Settings ticks
it off without any clicking.
"""
import json
import os
import plistlib
import subprocess

from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess

from ..profile import current
from . import hotkeys

APP = os.environ.get("FLIPPY_APP")  # set by Flippy.app's launcher; None when run from a terminal
AGENT_LABEL = current().bundle_id
AGENT = os.path.expanduser(f"~/Library/LaunchAgents/{AGENT_LABEL}.plist")
SCREEN_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
ACCESSIBILITY_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"


# ---- checks
def claude_logged_in():
    from ..providers import CONNECTION_STATUS
    return CONNECTION_STATUS["claude"] is True


def codex_logged_in():
    from ..providers import CONNECTION_STATUS
    return CONNECTION_STATUS["codex"] is True


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


def temporary_path(app):
    """Flippy running from the disk image or a quarantine copy (App Translocation): the path is gone after
    ejecting or a restart, so a login item there would open nothing."""
    return bool(app) and (app.startswith("/Volumes/") or "/AppTranslocation/" in app)


def installed():
    return bool(APP and os.path.isdir(APP)) and not temporary_path(APP)


def login_item_on():
    if current().demo:
        return False
    return os.path.exists(AGENT)


def state():
    """Everything the Setup page shows, as plain data."""
    app = os.path.abspath(APP) if installed() else None
    home = os.path.expanduser("~")
    return {
        "claude": claude_logged_in(), "codex": codex_logged_in(),
        "screen": screen_ok(), "accessibility": hotkeys.accessibility_trusted(),
        "login_item": login_item_on(), "login_item_allowed": installed() and not current().demo,
        "app": app and ("~" + app[len(home):] if app.startswith(home + os.sep) else app),
        "app_name": app and os.path.basename(app),
    }


# ---- actions
def terminal_env():
    """The environment for opening Terminal: without Flippy's own variables, which a Terminal started from here
    would pass on to every shell in it (FLIPPY_BUNDLED there made later Flippy commands act like the app)."""
    return {k: v for k, v in os.environ.items()
            if not k.startswith(("FLIPPY_", "PYTHON")) and k not in ("SSL_CERT_FILE", "ANTHROPIC_API_KEY")}


def open_login_terminal():
    """Run `claude` in Terminal so the user can /login with their Pro/Max account."""
    cmd = f"unset ANTHROPIC_API_KEY; '{claude_cli()}'"
    script = f'tell application "Terminal" to do script "{cmd}"\ntell application "Terminal" to activate'
    subprocess.Popen(["osascript", "-e", script], env=terminal_env())


def open_codex_login():
    # The owner completes Codex's native browser flow, into Flippy's own Codex home; Flippy never handles tokens.
    from ..codex_provider import codex_executable, login_command
    cli = codex_executable()  # not only PATH: apps get a minimal one
    if not cli:
        subprocess.Popen(["open", "https://developers.openai.com/codex/cli/"])
        return
    script = 'tell application "Terminal" to do script ' + json.dumps(login_command(cli))
    subprocess.Popen(["osascript", "-e", script], env=terminal_env())


def ask_screen():
    CGRequestScreenCaptureAccess()  # the system prompt (only the first time)
    subprocess.Popen(["open", SCREEN_PANE])


def ask_accessibility():
    from . import ax
    ax.ask_trust()  # macOS's prompt, and Flippy added to the list
    subprocess.Popen(["open", ACCESSIBILITY_PANE])


def restart():
    """macOS applies Screen Recording only to newly started processes."""
    from . import ui
    ui.PLATFORM.restart()


def reveal():
    if installed():
        from .permission_buddy import reveal_app
        reveal_app(APP)


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
    if not APP or temporary_path(APP):
        return
    os.makedirs(os.path.dirname(AGENT), exist_ok=True)
    with open(AGENT, "wb") as f:
        plistlib.dump({"Label": AGENT_LABEL, "ProgramArguments": ["/usr/bin/open", "-g", APP], "RunAtLoad": True}, f)


ACTIONS = {
    "claude": open_login_terminal, "codex": open_codex_login, "screen": ask_screen,
    "accessibility": ask_accessibility, "restart": restart, "reveal": reveal,
    "login_on": lambda: set_login_item(True), "login_off": lambda: set_login_item(False),
}


def act(name):
    if name not in ACTIONS:
        raise ValueError(f"unknown setup step {name}")
    ACTIONS[name]()
