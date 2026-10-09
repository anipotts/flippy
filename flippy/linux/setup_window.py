"""First-run setup on COSMIC: log in to Claude, add Flippy's keyboard shortcuts, optionally open at login.

COSMIC needs no permissions for Flippy (screenshots go through the portal), so
there are only two steps. The shortcuts are written into COSMIC's custom
shortcuts file (backed up first), which COSMIC picks up right away.
"""
import os
import shutil
import subprocess
import shlex

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import desktop  # noqa: E402
from .settings_window import SHORTCUTS, flippy_shortcuts, pretty_accel  # noqa: E402
from .. import settings

ASK = os.path.expanduser("~/.local/bin/flippy-ask")

# (what, flippy-ask args, COSMIC modifiers, key or None)
WANTED = [("Ask about the screen", "", ["Super", "Shift"], "space"),
          ("Circle something, then ask", "draw", ["Super", "Alt"], None),
          ("Check a video edit", "video", ["Super", "Shift"], "v"),
          ("Pause / resume a walkthrough", "pause-toggle", ["Super"], "p")]


def claude_logged_in():
    from ..providers import CONNECTION_STATUS
    return CONNECTION_STATUS["claude"] is True


def needs_setup():
    from ..providers import setup_ready
    return not setup_ready()


def claude_cli():
    """The CLI the Agent SDK uses: its bundled copy, else `claude` on PATH."""
    import claude_agent_sdk
    bundled = os.path.join(os.path.dirname(claude_agent_sdk.__file__), "_bundled", "claude")
    return bundled if os.path.exists(bundled) else "claude"


def open_login_terminal():
    """Run `claude` in a terminal so they can /login with their Pro/Max account."""
    cmd = f"unset ANTHROPIC_API_KEY; '{claude_cli()}'; exec $SHELL"
    for term in (["gnome-terminal", "--"], ["x-terminal-emulator", "-e"], ["kgx", "--"], ["xterm", "-e"]):
        if shutil.which(term[0]):
            subprocess.Popen(term + ["sh", "-c", cmd], start_new_session=True)
            return True
    return False


def open_codex_login():
    from ..codex_provider import codex_executable
    cli = codex_executable()  # not only PATH: apps get a minimal one
    if not cli:
        subprocess.Popen(["xdg-open", "https://developers.openai.com/codex/cli/"])
        return False
    cmd = "unset OPENAI_API_KEY CODEX_API_KEY; " + shlex.quote(cli) + " -c 'forced_login_method=\"chatgpt\"' login"
    for term in (["gnome-terminal", "--"], ["x-terminal-emulator", "-e"], ["kgx", "--"], ["xterm", "-e"]):
        if shutil.which(term[0]):
            subprocess.Popen(term + ["sh", "-c", cmd], start_new_session=True)
            return True
    return False


def _entry(mods, key, args):
    lines = ["    (\n", "        modifiers: [\n"]
    lines += [f"            {m},\n" for m in mods]
    lines.append("        ],\n")
    if key:
        lines.append(f'        key: "{key}",\n')
    lines.append(f'    ): Spawn("{(ASK + " " + args).strip()}"),\n')
    return "".join(lines)


def add_shortcuts(which, path=SHORTCUTS):
    """Append the WANTED entries at `which` (indexes) to COSMIC's custom shortcuts, keeping a backup."""
    try:
        with open(path) as f:
            text = f.read()
    except FileNotFoundError:
        text = "{\n}"
    body = text.rstrip()
    if not body.endswith("}"):
        raise ValueError(f"don't understand {path}; add the shortcuts in COSMIC Settings instead")
    body = body[:-1].rstrip()
    if not body.endswith(("{", ",")):
        body += ","
    new = body + "\n" + "".join(_entry(WANTED[i][2], WANTED[i][3], WANTED[i][1]) for i in which) + "}\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak-flippy")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(new)
    os.replace(tmp, path)


class SetupWindow(Adw.Window):
    def __init__(self, app, open_settings, on_close):
        Adw.init()
        super().__init__(application=app, title="Set up Flippy", default_width=560, modal=False)
        self.open_settings = open_settings
        self.connect("close-request", lambda *_: on_close() or False)
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title="Welcome to Flippy", description="Ask about anything on your screen and "
                                 "Flippy points at it. Two quick steps and you're set.")
        self.login_row = Adw.ActionRow(title="1. Log in to Claude",
                                       subtitle="Flippy uses your Claude Pro or Max plan through Claude Code, not "
                                                "API credits. In the terminal that opens, type /login.")
        self.login_mark = Gtk.Image(valign=Gtk.Align.CENTER)
        self.login_row.add_prefix(self.login_mark)
        btn = Gtk.Button(label="Log in…", valign=Gtk.Align.CENTER)
        btn.connect("clicked", lambda *_: open_login_terminal())
        self.login_row.add_suffix(btn)
        g.add(self.login_row)
        codex = Adw.ActionRow(title="ChatGPT via Codex", subtitle="API keys are refused. Included-only credit enforcement is still under verification.")
        self.codex_mark = Gtk.Image(valign=Gtk.Align.CENTER)
        codex.add_prefix(self.codex_mark)
        sign_in = Gtk.Button(label="Sign in…", valign=Gtk.Align.CENTER)
        sign_in.connect("clicked", lambda *_: open_codex_login())
        codex.add_suffix(sign_in)
        g.add(codex)
        from .settings_window import combo_row
        g.add(combo_row("Use", "Choose one if both subscriptions are connected", "provider", "mode", settings.options("provider", "mode")))
        page.add(g)

        self.keys = Adw.PreferencesGroup(title="2. Keyboard shortcuts",
                                         description="COSMIC runs these; Flippy starts itself on the first press.")
        page.add(self.keys)
        self.key_rows = []

        g = Adw.PreferencesGroup(title="Options")
        login = Adw.SwitchRow(title="Open Flippy at login", subtitle="So its panel icon, help mode and update "
                              "checks are on from the start. Otherwise it starts on your first shortcut.",
                              active=desktop.autostart_on())
        login.connect("notify::active", lambda r, _p: desktop.set_autostart(r.get_active()))
        g.add(login)
        page.add(g)

        g = Adw.PreferencesGroup()
        g.add(_button_row("Help when you're stuck, tips, settings", "All in Flippy's icon in the panel",
                          "Settings…", self.open_settings))
        done = Gtk.Button(label="Done", halign=Gtk.Align.END, margin_top=12)
        done.add_css_class("suggested-action")
        done.connect("clicked", lambda *_: self.close())
        g.add(done)
        page.add(g)
        self.set_content(page)
        self._refresh()
        self.timer = GLib.timeout_add_seconds(2, lambda: self._refresh() or True)  # notice the login finishing
        self.connect("close-request", lambda *_: GLib.source_remove(self.timer) or False)

    def _refresh(self):
        ok = claude_logged_in()
        self.login_mark.set_from_icon_name("emblem-ok-symbolic" if ok else "dialog-warning-symbolic")
        from ..providers import CONNECTION_STATUS
        self.codex_mark.set_from_icon_name("emblem-ok-symbolic" if CONNECTION_STATUS["codex"] is True else "dialog-warning-symbolic")
        have = {args for _, args in flippy_shortcuts()}
        bound = {args: pretty_accel(accel) for accel, args in flippy_shortcuts()}
        key = tuple(sorted(bound.items()))
        if getattr(self, "_keys_shown", None) == key:
            return
        self._keys_shown = key
        for row in self.key_rows:
            self.keys.remove(row)
        self.key_rows = []
        missing = []
        for i, (what, args, mods, k) in enumerate(WANTED):
            row = Adw.ActionRow(title=what, subtitle=f"flippy-ask {args}".strip())
            if args in have:
                row.add_suffix(Gtk.Label(label=bound[args], css_classes=["dim-label"]))
            else:
                row.add_suffix(Gtk.Label(label="not set", css_classes=["dim-label"]))
                missing.append(i)
            self.keys.add(row)
            self.key_rows.append(row)
        if missing:
            labels = ", ".join("+".join(WANTED[i][2] + ([WANTED[i][3].title()] if WANTED[i][3] else [])) for i in missing)
            row = _button_row("Add the missing shortcuts", labels, "Add", lambda: self._add(missing))
            self.keys.add(row)
            self.key_rows.append(row)
        row = _button_row("Change them", None, "Open COSMIC Settings",
                          lambda: subprocess.Popen(["cosmic-settings", "keyboard"]))
        self.keys.add(row)
        self.key_rows.append(row)

    def _add(self, which):
        try:
            add_shortcuts(which)
        except (OSError, ValueError) as e:
            dlg = Adw.MessageDialog(transient_for=self, heading="Couldn't add the shortcuts", body=str(e))
            dlg.add_response("ok", "OK")
            dlg.present()
        self._refresh()


def _button_row(title, subtitle, label, callback):
    row = Adw.ActionRow(title=title, subtitle=subtitle or "")
    btn = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
    btn.connect("clicked", lambda *_: callback())
    row.add_suffix(btn)
    return row
