"""First-run setup on COSMIC: connect a subscription, Flippy's keyboard shortcuts, optionally open at login.

The same window as flippy/mac/setup_window.py, in the same look (flippy/linux/style.py). COSMIC needs no
permissions for Flippy (screenshots go through the portal), so there are two steps, not three. The shortcuts
live in COSMIC's custom shortcuts file: Flippy can add the missing ones there (backed up first), and COSMIC picks
them up right away.
"""
import os
import shutil
import subprocess
import shlex

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from . import desktop, style  # noqa: E402
from .settings_window import SHORTCUTS, flippy_shortcuts, pretty_accel  # noqa: E402
from .. import settings  # noqa: E402
from ..profile import current  # noqa: E402

ASK = os.path.expanduser("~/.local/bin/flippy-ask")
ASSETS = os.path.join(os.path.dirname(__file__), "assets")
WIDTH = 560

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
    from ..codex_provider import child_environment, codex_executable
    cli = codex_executable()  # not only PATH: apps get a minimal one
    if not cli:
        subprocess.Popen(["xdg-open", "https://developers.openai.com/codex/cli/"])
        return False
    # Codex installed with npm is a node script: the terminal needs node on its PATH, and an app's PATH (a
    # shortcut's, the app library's) often hasn't got it. Keep the window open if signing in fails, to read why.
    cmd = ("unset OPENAI_API_KEY CODEX_API_KEY; export PATH=" + shlex.quote(child_environment()["PATH"]) + "; "
           + shlex.quote(cli) + " -c 'forced_login_method=\"chatgpt\"' login"
           + " || { echo; echo 'Signing in to Codex failed (see above). Press Enter to close.'; read _; }")
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


def provider_prompt(mode, claude, codex):
    """The line under Use: (text, bright, Use needs a pick). With both connected and Use on Automatic nothing is
    picked, so setup can't finish: ask for one."""
    if mode == "auto" and claude and codex:
        return "Both are connected. Pick Claude or ChatGPT under Use to finish setup.", True, True
    if mode != "auto" and not {"claude": claude, "codex": codex}.get(mode):
        return (("Claude" if mode == "claude" else "ChatGPT") + " isn't connected yet. Connect it above, or pick "
                "the other."), True, False
    return "You can switch any time in Settings → Models.", False, False


def accel_tokens(accel):
    """"<Super><Shift>space" -> the keycaps ["Super", "Shift", "Space"]."""
    return pretty_accel(accel).split("+") if accel else []


def missing_text(missing):
    """"Not in COSMIC yet: circle something, then ask (Super+Alt)." for the WANTED indexes that aren't bound."""
    def keys(mods, key):
        return "+".join(mods + ([key.title()] if key else []))
    return "Not in COSMIC yet: " + ", ".join(
        f"{WANTED[i][0][0].lower()}{WANTED[i][0][1:]} ({keys(WANTED[i][2], WANTED[i][3])})" for i in missing) + "."


def _grow(widget):
    widget.set_hexpand(True)
    widget.set_valign(Gtk.Align.CENTER)
    return widget


def _rule(margin=0, inset=False):
    line = style.rule()
    line.set_margin_top(margin)
    line.set_margin_bottom(margin)
    if inset:
        line.set_margin_start(24)
        line.set_margin_end(24)
    return line


class SetupWindow(Gtk.Window):
    CARD_PAD = 14

    def __init__(self, app, open_settings, on_close):
        Adw.init()
        super().__init__(application=app, title="Flippy", default_width=WIDTH, resizable=False)
        style.apply(self)
        self.set_titlebar(style.headerbar("Flippy"))
        self.open_settings = open_settings
        self.marks, self.provider_buttons = {}, {}
        self._keys_shown, self._missing = None, []
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=24, margin_end=24, margin_top=16,
                       margin_bottom=16)
        head = Gtk.Box(spacing=16)
        head.append(style.mark(60))
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER)
        words.append(style.label("Hi, I'm Flippy.", "title-1"))
        words.append(style.label("Ask about anything on your screen. I'll point it out.", "muted"))
        head.append(words)
        body.append(head)
        body.append(_rule(12))

        body.append(style.section(1, "Connect", "Use the subscription you've already got."))
        cards = Gtk.Box(spacing=12, homogeneous=True, margin_top=16)
        cards.append(self._provider_card("claude", "Claude", "claude.png", open_login_terminal))
        cards.append(self._provider_card("codex", "ChatGPT", "openai.png", open_codex_login))
        body.append(cards)
        use = Gtk.Box(spacing=12, margin_top=14)
        words = _grow(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2))
        words.append(style.label("Use", "heading"))
        words.append(style.label("Auto picks the only connected subscription.", "muted", "tiny"))
        use.append(words)
        options = settings.options("provider", "mode")
        self.provider_values = [v for v, _ in options]
        self.provider_choice = Gtk.DropDown.new_from_strings([lab for _, lab in options])
        self.provider_choice.set_size_request(230, -1)
        self.provider_choice.set_valign(Gtk.Align.CENTER)
        self.provider_choice.update_property([Gtk.AccessibleProperty.LABEL], ["Subscription to use"])
        mode = settings.get("provider", "mode")
        self.provider_choice.set_selected(self.provider_values.index(mode) if mode in self.provider_values else 0)
        self.provider_choice.connect("notify::selected", self._choose_provider)
        use.append(self.provider_choice)
        body.append(use)
        self.provider_note = style.label("", "small", wrap=True, width=WIDTH - 48)  # see _refresh
        self.provider_note.set_margin_top(10)
        body.append(self.provider_note)
        body.append(_rule(14))

        body.append(style.section(2, "Your shortcut", "That's how you call me, from any app."))
        keys = Gtk.Box(spacing=12, margin_top=14, margin_start=44)
        self.shortcut_box = _grow(Gtk.Box())
        keys.append(self.shortcut_box)
        self.edit_button = style.button("Edit…", self._edit)
        self.edit_button.set_valign(Gtk.Align.CENTER)
        self.edit_button.set_size_request(82, -1)
        self.edit_button.update_property([Gtk.AccessibleProperty.LABEL], ["See Flippy's shortcuts"])
        keys.append(self.edit_button)
        body.append(keys)
        note = style.label("There are more, like circling something or checking a video. Edit… lists them all; "
                           "you change them in COSMIC Settings.", "muted", "tiny", wrap=True, width=WIDTH - 92)
        note.set_margin_start(44)
        note.set_margin_top(10)
        body.append(note)
        self.missing_row = Gtk.Box(spacing=12, margin_top=12, margin_start=44)
        self.missing_note = _grow(style.label("", "small", wrap=True, width=WIDTH - 92 - 12 - 100))  # room for Add
        self.missing_row.append(self.missing_note)
        self.add_button = style.button("Add them", lambda: self._add(self._missing))
        self.add_button.set_valign(Gtk.Align.CENTER)
        self.add_button.set_size_request(82, -1)
        self.missing_row.append(self.add_button)
        body.append(self.missing_row)

        # the footer stays put; the body scrolls only on small screens
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                    child=body)
        monitor = Gdk.Display.get_default().get_monitors().get_item(0)
        scroll.set_max_content_height(max(320, monitor.get_geometry().height - 260) if monitor else 700)
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        footer.append(_rule(inset=True))
        login = Gtk.Box(spacing=12, margin_start=24, margin_end=24, margin_top=9, margin_bottom=9)
        login.append(_grow(style.label("Launch at login")))
        self.login_switch = Gtk.Switch(active=desktop.autostart_on(), valign=Gtk.Align.CENTER,
                                       sensitive=not current().demo)
        self.login_switch.update_property([Gtk.AccessibleProperty.LABEL], ["Launch Flippy at login"])
        self.login_switch.connect("notify::active", lambda sw, _p: desktop.set_autostart(sw.get_active()))
        login.append(self.login_switch)  # its right edge lines up with the buttons'
        footer.append(login)
        footer.append(style.rule())
        end = Gtk.Box(spacing=12, margin_start=24, margin_end=24, margin_top=12, margin_bottom=14)
        end.append(_grow(style.label("You stay in control.", "muted", "small")))
        self.done_button = style.button("Done", self.close)
        self.done_button.set_size_request(82, -1)
        end.append(self.done_button)
        footer.append(end)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.append(scroll)
        root.append(footer)
        self.set_child(root)
        self.set_default_widget(self.done_button)
        self._refresh()
        self.timer = GLib.timeout_add_seconds(2, lambda: self._refresh() or True)  # notice a login finishing

        def closed(*_):
            GLib.source_remove(self.timer)
            on_close()
            return False
        self.connect("close-request", closed)

    def _provider_card(self, key, title, asset, callback):
        """Same padding on every side; the logo, the name and status, and the button centered top to bottom."""
        card = style.card()
        inner = Gtk.Box(spacing=12, margin_top=self.CARD_PAD, margin_bottom=self.CARD_PAD,
                        margin_start=self.CARD_PAD, margin_end=self.CARD_PAD, hexpand=True)
        logo = Gtk.Picture.new_for_filename(os.path.join(ASSETS, asset))
        logo.set_size_request(30, 30)
        logo.set_can_shrink(True)
        logo.set_valign(Gtk.Align.CENTER)
        logo.update_property([Gtk.AccessibleProperty.LABEL], [title + " logo"])
        inner.append(logo)
        words = _grow(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2))
        words.append(style.label(title, "heading"))
        self.marks[key] = style.label("", "muted", "tiny")
        words.append(self.marks[key])
        inner.append(words)
        action = style.button("Log in…", callback)
        action.set_valign(Gtk.Align.CENTER)
        action.update_property([Gtk.AccessibleProperty.LABEL], ["Connect " + title])
        inner.append(action)
        self.provider_buttons[key] = action
        card.append(inner)
        return card

    # ---- actions
    def _choose_provider(self, dropdown, _param):
        value = self.provider_values[dropdown.get_selected()]
        if value != settings.get("provider", "mode"):
            settings.set("provider", "mode", value)
        self._refresh()

    def _edit(self):
        """Settings, on its Hotkeys page: COSMIC runs the shortcuts, and that page says where to change them."""
        self.open_settings()
        from .settings_window import SettingsWindow
        app = self.get_application()
        for win in app.get_windows() if app else ():
            if isinstance(win, SettingsWindow):
                win.show_page("hotkeys")

    def _add(self, which):
        try:
            add_shortcuts(which)
        except (OSError, ValueError) as e:
            dlg = Adw.MessageDialog(transient_for=self, heading="Couldn't add the shortcuts", body=str(e))
            dlg.add_response("ok", "OK")
            dlg.present()
        self._refresh()

    # ---- state
    def _refresh(self):
        from ..providers import CONNECTION_STATUS
        claude = claude_logged_in()
        codex = CONNECTION_STATUS["codex"] is True
        for key, ok, connect in (("claude", claude, "Log in…"), ("codex", codex, "Sign in…")):
            self.marks[key].set_label("Connected" if ok else "Not connected")
            self.provider_buttons[key].set_label("Reconnect…" if ok else connect)
        mode = settings.get("provider", "mode")
        if mode in self.provider_values and self.provider_choice.get_selected() != self.provider_values.index(mode):
            self.provider_choice.set_selected(self.provider_values.index(mode))
        text, bright, pick = provider_prompt(mode, claude, codex)
        self.provider_note.set_label(text)
        for widget, cls, on in ((self.provider_note, "muted", not bright), (self.provider_choice, "attention", pick)):
            (widget.add_css_class if on else widget.remove_css_class)(cls)

        bound = {args: accel for accel, args in flippy_shortcuts()}
        shown = tuple(sorted(bound.items()))
        if shown == self._keys_shown:
            return
        self._keys_shown = shown
        while (child := self.shortcut_box.get_first_child()) is not None:
            self.shortcut_box.remove(child)
        if "" in bound:
            self.shortcut_box.append(style.keycaps(accel_tokens(bound[""])))
            self.shortcut_box.update_property([Gtk.AccessibleProperty.LABEL],
                                              ["Ask about the screen: " + pretty_accel(bound[""])])
        else:
            self.shortcut_box.append(style.label("Not set up yet", "muted"))
        self._missing = [i for i, (_, args, _, _) in enumerate(WANTED) if args not in bound]
        self.missing_row.set_visible(bool(self._missing))
        self.missing_note.set_label(missing_text(self._missing) if self._missing else "")
