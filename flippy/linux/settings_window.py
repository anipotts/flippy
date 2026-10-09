"""Flippy settings window (libadwaita). Every change is saved and applied immediately.

A normal window on purpose: on COSMIC, layer surfaces can't be closed safely (see daemon.py).
"""
import os
import re
import subprocess

import cairo
import gi

gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import pointer_editor  # noqa: E402
from .. import pointers, settings, themes  # noqa: E402

_adw_ready = False

MODELS = settings.options('claude', 'model')
EFFORTS = settings.options('claude', 'effort')
IMAGES = settings.options('claude', 'image')
POINTERS = settings.options('look', 'pointer')
PACES = settings.options('timing', 'step_pace')
SHORTCUTS = os.path.expanduser("~/.config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom")


def combo_row(title, subtitle, section, key, options):
    row = Adw.ComboRow(title=title, subtitle=subtitle or "")
    row.set_model(Gtk.StringList.new([label for _, label in options]))
    values = [v for v, _ in options]
    current = settings.get(section, key)
    row.set_selected(values.index(current) if current in values else 0)
    row.connect("notify::selected", lambda r, _p: settings.set(section, key, values[r.get_selected()]))
    return row


def spin_row(title, subtitle, section, key):
    spec = settings.SETTINGS[section, key]
    adj = Gtk.Adjustment(value=settings.get(section, key), lower=spec.minimum, upper=spec.maximum, step_increment=spec.step)
    row = Adw.SpinRow(title=title, subtitle=subtitle or "", adjustment=adj, digits=spec.digits)
    as_int = isinstance(settings.DEFAULTS[section][key], int)
    row.connect("notify::value", lambda r, _p: settings.set(section, key, int(r.get_value()) if as_int
                                                             else round(r.get_value(), spec.digits)))
    return row


def button_row(title, subtitle, label, callback, css=None):
    row = Adw.ActionRow(title=title, subtitle=subtitle or "")
    btn = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
    if css:
        btn.add_css_class(css)
    btn.connect("clicked", lambda *_: callback())
    row.add_suffix(btn)
    return row


class ThemePicker(Gtk.FlowBox):
    """Clickable live thumbnails of each theme's answer card."""

    SAMPLE = themes.Card(text="The pointer glides here and the panel follows it.", header="Workspaces",
                         steps=["Launcher", "Workspaces"], step=1, progress=0.45, meta="OPUS · LOW", follow=True)

    def __init__(self):
        super().__init__(selection_mode=Gtk.SelectionMode.NONE, column_spacing=12, row_spacing=12,
                         max_children_per_line=2, min_children_per_line=2, homogeneous=True)
        self.buttons = {}
        group = None
        for key, theme in themes.THEMES.items():
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            area = Gtk.DrawingArea(content_width=260, content_height=150)
            area.set_draw_func(self._draw_thumb, theme)
            box.append(area)
            box.append(Gtk.Label(label=theme.name))
            btn = Gtk.ToggleButton(child=box)
            btn.add_css_class("flat")
            if group:
                btn.set_group(group)
            group = group or btn
            btn.set_active(settings.get("look", "theme") == key)
            btn.connect("toggled", lambda b, k=key: b.get_active() and settings.set("look", "theme", k))
            self.buttons[key] = btn
            self.append(btn)

    def _draw_thumb(self, area, cr, w, h, theme):
        g = cairo.LinearGradient(0, 0, w, h)
        g.add_color_stop_rgb(0, 0.33, 0.2, 0.3)
        g.add_color_stop_rgb(1, 0.13, 0.11, 0.24)
        cr.set_source(g)
        cr.paint()
        opts = {"text_size": 15, "card_opacity": settings.get("look", "card_opacity")}
        cw, ch = theme.size(self.SAMPLE, opts)
        k = min((w - 50) / cw, (h - 16) / ch, 1.0)
        cr.save()
        cr.translate(44, (h - ch * k) / 2)
        cr.scale(k, k)
        theme.draw(cr, 0, 0, cw, ch, self.SAMPLE, 1.2, opts)
        cr.restore()
        style = settings.get("look", "pointer")
        themes.draw_pointer(cr, theme, theme.pointer if style == "theme" else style, 22, 18, 1.0, 0.45, 10_000)


def switch_row(title, subtitle, section, key):
    row = Adw.SwitchRow(title=title, subtitle=subtitle or "", active=settings.get(section, key))
    row.connect("notify::active", lambda r, _p: settings.set(section, key, r.get_active()))
    return row


HELP_MODES = settings.options('help', 'mode')


class SettingsWindow(Adw.PreferencesWindow):
    def __init__(self, app, on_preview, on_reset, command=lambda cmd: None):
        global _adw_ready
        if not _adw_ready:
            Adw.init()
            _adw_ready = True
        super().__init__(application=app, title="Flippy Settings", default_width=640, default_height=760)
        self.set_modal(False)  # Adw.PreferencesWindow is modal by default, which blocks the pointer editors
        self.set_search_enabled(False)
        self.command = command
        self.add(self._appearance(on_preview))
        self.add(self._claude(on_reset))
        self.add(self._actions())
        self.add(self._timing(on_preview))
        self.add(self._help())
        self.add(self._hotkeys())
        self._listener = lambda s, k, v: ((s == "look" and self.picker_redraw())
                                        or (s == "help" and self._fill_apps())
                                        or (s == "act" and k == "allowed_apps" and self._fill_allowed_apps()))
        settings.on_change(self._listener)
        self.connect("close-request", lambda *_: settings.off_change(self._listener) or False)

    # ---- pointer choices (built-ins + custom)
    def _pointer_options(self):
        return POINTERS + [(pointers.PREFIX + n, f"Custom: {n}") for n in pointers.names()]

    def _fill_pointer_row(self):
        self._filling = True
        opts = self._pointer_options()
        self._pointer_values = [v for v, _ in opts]
        self.pointer_row.set_model(Gtk.StringList.new([label for _, label in opts]))
        cur = settings.get("look", "pointer")
        self.pointer_row.set_selected(self._pointer_values.index(cur) if cur in self._pointer_values else 0)
        self._filling = False

    def _pointer_chosen(self, row, _p):
        if not self._filling and row.get_selected() < len(self._pointer_values):
            settings.set("look", "pointer", self._pointer_values[row.get_selected()])
            self._update_custom_buttons()

    def _current_custom(self):
        cur = settings.get("look", "pointer")
        return cur[len(pointers.PREFIX):] if cur.startswith(pointers.PREFIX) else None

    def _update_custom_buttons(self):
        on = self._current_custom() is not None
        self.edit_btn.set_sensitive(on)
        self.del_btn.set_sensitive(on)

    def _pointer_saved(self, name):
        settings.set("look", "pointer", pointers.PREFIX + name)
        self._fill_pointer_row()
        self._update_custom_buttons()
        self.picker_redraw()

    def _add_image(self):
        pointer_editor.import_image(self, self.get_application(), self._pointer_saved)

    def _draw_new(self):
        ed = pointer_editor.PixelEditor(self.get_application(), self._pointer_saved)
        ed.set_transient_for(self)
        ed.present()

    def _edit_current(self):
        name = self._current_custom()
        if name:
            pointer_editor.edit(self.get_application(), self._pointer_saved, name)

    def _delete_current(self):
        name = self._current_custom()
        if not name:
            return
        dlg = Adw.MessageDialog(transient_for=self, heading=f"Delete “{name}”?", body="This can't be undone.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("delete", "Delete")
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(d, resp):
            if resp == "delete":
                settings.set("look", "pointer", "theme")
                pointers.delete(name)
                self._fill_pointer_row()
                self._update_custom_buttons()
                self.picker_redraw()
        dlg.connect("response", on_response)
        dlg.present()

    def picker_redraw(self):
        for btn in self.picker.buttons.values():
            btn.get_child().get_first_child().queue_draw()

    # ---- pages
    def _appearance(self, on_preview):
        page = Adw.PreferencesPage(title="Appearance", icon_name="applications-graphics-symbolic")
        g = Adw.PreferencesGroup(title="Theme", description="Sets the answer panel, pointer, pen and question box together.")
        self.picker = ThemePicker()
        g.add(self.picker)
        page.add(g)

        g = Adw.PreferencesGroup(title="Pointer and panel")
        self.pointer_row = Adw.ComboRow(title="Pointer", subtitle="Override the theme's pointer")
        self._fill_pointer_row()
        self.pointer_row.connect("notify::selected", self._pointer_chosen)
        g.add(self.pointer_row)
        custom = Adw.ActionRow(title="Custom pointers", subtitle="Upload an image or draw pixel art")
        for label, cb in (("Add image…", self._add_image), ("Draw…", self._draw_new)):
            b = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
            b.connect("clicked", lambda *_, f=cb: f())
            custom.add_suffix(b)
        self.edit_btn = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Edit")
        self.edit_btn.connect("clicked", lambda *_: self._edit_current())
        self.del_btn = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Delete")
        self.del_btn.add_css_class("destructive-action")
        self.del_btn.connect("clicked", lambda *_: self._delete_current())
        custom.add_suffix(self.edit_btn)
        custom.add_suffix(self.del_btn)
        g.add(custom)
        self._update_custom_buttons()
        g.add(spin_row("Pointer size", None, "look", "pointer_size"))
        g.add(spin_row("Text size", "Answer text, in px", "look", "text_size"))
        g.add(spin_row("Panel opacity", None, "look", "card_opacity"))
        g.add(combo_row("Playback controls", "Clickable play/pause/step buttons on the answer panel", "look", "controls",
                        settings.options("look", "controls")))
        page.add(g)

        g = Adw.PreferencesGroup()
        g.add(button_row("Preview", "Plays a short fake walkthrough on your screen", "Preview", on_preview, "suggested-action"))
        page.add(g)
        return page

    def _claude(self, on_reset):
        page = Adw.PreferencesPage(title="Models", icon_name="dialog-information-symbolic")
        connection = Adw.PreferencesGroup(title="Connection", description="Uses your signed-in subscription. Changing connections starts a fresh session.")
        connection.add(combo_row("Provider", None, "provider", "mode", settings.options("provider", "mode")))
        page.add(connection)
        g = Adw.PreferencesGroup(title="Claude", description="Model and effort apply when Claude is selected.")
        g.add(combo_row("Model", None, "claude", "model", MODELS))
        g.add(combo_row("Effort", "Higher thinks more carefully but answers slower", "claude", "effort", EFFORTS))
        g.add(combo_row("Screenshot detail", "Sharper helps with tiny icons but uses more of your plan",
                        "claude", "image", IMAGES))
        page.add(g)
        codex = Adw.PreferencesGroup(title="Codex / ChatGPT", description="Uses the Codex sign-in. Model and effort apply when Codex is selected.")
        model = Adw.EntryRow(title="Model (default uses the account model)")
        model.set_text(settings.get("codex", "model"))
        model.set_show_apply_button(True)
        model.connect("apply", self._codex_model_changed)
        codex.add(model)
        codex.add(combo_row("Effort", None, "codex", "effort", settings.options("codex", "effort")))
        page.add(codex)
        g = Adw.PreferencesGroup(title="Session")
        g.add(button_row("Start fresh session", "Forget the conversation so far", "Reset", on_reset))
        page.add(g)
        g = Adw.PreferencesGroup(title="Updates")
        g.add(switch_row("Check for updates daily", "When a new version is out, Flippy offers to install it",
                         "updates", "check"))
        g.add(button_row("Check now", None, "Check", lambda: self.command("update")))
        page.add(g)
        return page

    def _codex_model_changed(self, row):
        try:
            settings.set("codex", "model", row.get_text().strip())
        except ValueError:
            row.set_text(settings.get("codex", "model"))

    def _actions(self):
        page = Adw.PreferencesPage(title="Automation", icon_name="input-mouse-symbolic")
        group = Adw.PreferencesGroup(title="Desktop tasks", description="Applies to /act desktop input on macOS. Questions and walkthroughs stay tool-free.")
        group.add(combo_row("Approval", None, "act", "mode", settings.options("act", "mode")))
        group.add(Adw.ActionRow(title="Ask once per app", subtitle="Approve an app when a task first needs it; approvals are remembered."))
        group.add(Adw.ActionRow(title="Act automatically", subtitle="Allows input without an approval card. Stop halts further input."))
        group.add(Adw.ActionRow(title="Ask before every input", subtitle="Shows each proposed input for approval."))
        strict, automatic = settings.ACT_LIMITS["every_input"], settings.ACT_LIMITS["auto"]
        group.add(Adw.ActionRow(title="Task bounds", subtitle=f"Every input: {strict.max_actions} inputs, {strict.timeout_seconds // 60} minutes. Other modes: {automatic.max_actions} inputs, {automatic.timeout_seconds // 60} minutes."))
        page.add(group)
        self.allowed_group = Adw.PreferencesGroup(title="Remembered apps", description="Removing an app makes the next task ask again in Ask once per app mode.")
        self.allowed_rows = []
        page.add(self.allowed_group)
        self._fill_allowed_apps()
        return page

    def _fill_allowed_apps(self):
        for row in self.allowed_rows:
            self.allowed_group.remove(row)
        self.allowed_rows = []
        apps = settings.get("act", "allowed_apps")
        for app in apps:
            row = Adw.ActionRow(title=GLib.markup_escape_text(app))
            remove = Gtk.Button(icon_name="list-remove-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Remove")
            remove.connect("clicked", lambda *_, app=app: settings.remove_allowed_app(app))
            row.add_suffix(remove)
            self.allowed_group.add(row)
            self.allowed_rows.append(row)
        if not apps:
            row = Adw.ActionRow(title="None yet")
            self.allowed_group.add(row)
            self.allowed_rows.append(row)

    def _timing(self, on_preview):
        page = Adw.PreferencesPage(title="Timing", icon_name="preferences-system-time-symbolic")
        g = Adw.PreferencesGroup(title="Answers")
        g.add(spin_row("Stay up for", "Seconds after the answer finishes", "timing", "show_seconds"))
        g.add(spin_row("Longest stay", "Cap for long answers, in seconds", "timing", "max_show_seconds"))
        page.add(g)
        g = Adw.PreferencesGroup(title="Walkthroughs")
        g.add(combo_row("Step pace", "How long each pointed step stays", "timing", "step_pace", PACES))
        g.add(spin_row("Playback speed", "Also on the Media Player/Y2K players' slider", "timing", "speed"))
        g.add(spin_row("Glide time", "Seconds for the pointer to travel between steps", "timing", "glide_seconds"))
        g.add(switch_row("Wait for my clicks", "Tutorials pause on steps you have to do until you click the thing",
                         "timing", "wait_for_clicks"))
        g.add(button_row("Try it", None, "Preview", on_preview))
        page.add(g)
        return page

    def _help(self):
        page = Adw.PreferencesPage(title="Help", icon_name="help-browser-symbolic")
        g = Adw.PreferencesGroup(title="Help mode", description="Flippy watches only the apps below, with simple "
                                 "local rules, and asks nothing of Claude until you press Help or Show me.")
        g.add(combo_row("When I'm learning an app", None, "help", "mode", HELP_MODES))
        page.add(g)
        self.apps_group = Adw.PreferencesGroup(title="Watched apps", description="Add the app in front from "
                                               "Flippy's panel icon → Watch &lt;app&gt;.")
        self.muted_group = Adw.PreferencesGroup(title="Don't ask in", description="Apps where you chose "
                                                "“Don't ask in <app>”.")
        page.add(self.apps_group)
        page.add(self.muted_group)
        self.app_rows = []
        self._fill_apps()
        return page

    def _fill_apps(self):
        for group, row in self.app_rows:
            group.remove(row)
        self.app_rows = []
        from .sensors import app_name
        for group, key, empty in ((self.apps_group, "apps", "None yet"), (self.muted_group, "muted", "None")):
            ids = sorted(settings.get_list("help", key))
            for app in ids:
                row = Adw.ActionRow(title=GLib.markup_escape_text(app_name(app)), subtitle=GLib.markup_escape_text(app))
                btn = Gtk.Button(icon_name="list-remove-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Remove")
                btn.add_css_class("flat")
                btn.connect("clicked", lambda *_, k=key, a=app: settings.set_list("help", k, settings.get_list("help", k) - {a}))
                row.add_suffix(btn)
                group.add(row)
                self.app_rows.append((group, row))
            if not ids:
                row = Adw.ActionRow(title=empty)
                group.add(row)
                self.app_rows.append((group, row))

    def _hotkeys(self):
        page = Adw.PreferencesPage(title="Hotkeys", icon_name="input-keyboard-symbolic")
        g = Adw.PreferencesGroup(title="Shortcuts", description="Set in COSMIC Settings → Keyboard → Custom shortcuts.")
        found = False
        for keys, cmd in flippy_shortcuts():
            found = True
            action = {"": "Ask a question", "draw": "Draw mode (circle something)",
                      "pause-toggle": "Pause / resume a walkthrough", "video": "Check a video edit"}.get(cmd, cmd)
            row = Adw.ActionRow(title=action, subtitle=f"flippy-ask {cmd}".strip())
            row.add_suffix(Gtk.ShortcutLabel(accelerator=keys, valign=Gtk.Align.CENTER))
            g.add(row)
        if not found:
            g.add(Adw.ActionRow(title="No Flippy shortcuts found",
                                subtitle="Add one that runs ~/.local/bin/flippy-ask"))
        g.add(button_row("Change shortcuts", None, "Open COSMIC Settings",
                         lambda: subprocess.Popen(["cosmic-settings", "keyboard"])))
        page.add(g)
        g = Adw.PreferencesGroup(title="Scripts")
        g.add(switch_row("Let scripts type", "flippy-ask type/key/tap send real keystrokes (for demos). Any program "
                         "running as you could use it. This is separate from /act approvals.", "automation", "clicks"))
        page.add(g)
        g = Adw.PreferencesGroup(title="In the question box")
        for cmd, what in (("/new", "Start a fresh session"), ("/settings", "Open this window"), ("Esc", "Close")):
            g.add(Adw.ActionRow(title=what, subtitle=cmd))
        page.add(g)
        g = Adw.PreferencesGroup(title="Config file")
        g.add(button_row(settings.PATH.replace(os.path.expanduser("~"), "~"), "Edit by hand if you like", "Open",
                         lambda: subprocess.Popen(["xdg-open", settings.PATH])))
        page.add(g)
        return page


def pretty_accel(accel):
    """"<Super><Shift>space" -> "Super+Shift+Space"."""
    mods = re.findall(r"<([^>]+)>", accel)
    key = re.sub(r"<[^>]+>", "", accel)
    return "+".join(mods + ([key[:1].upper() + key[1:]] if key else []))


def flippy_shortcuts():
    """[(gtk accelerator, flippy-ask args)] from COSMIC's custom shortcuts file."""
    try:
        text = open(SHORTCUTS).read()
    except OSError:
        return []
    out = []
    for m in re.finditer(r'\(\s*modifiers:\s*\[([^\]]*)\],(?:\s*key:\s*"([^"]+)",)?\s*\):\s*Spawn\("([^"]*flippy-ask[^"]*)"\)', text):
        mods = [x.strip() for x in m.group(1).split(",") if x.strip()]
        accel = "".join(f"<{'Control' if x == 'Ctrl' else x}>" for x in mods) + (m.group(2) or "")
        args = m.group(3).split("flippy-ask", 1)[1].strip()
        out.append((accel, args))
    return out
