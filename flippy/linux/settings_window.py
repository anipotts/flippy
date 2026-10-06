"""Flippy settings window (libadwaita). Every change is saved and applied immediately.

A normal window on purpose: on COSMIC, layer surfaces can't be closed safely (see daemon.py).
"""
import os
import re
import subprocess

import cairo
import gi

gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from . import pointer_editor  # noqa: E402
from .. import pointers, settings, themes  # noqa: E402

_adw_ready = False

MODELS = [("default", "Account default"), ("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku")]
EFFORTS = [("low", "Low (fastest)"), ("medium", "Medium"), ("high", "High"), ("max", "Max (slowest)")]
IMAGES = [(1366, "1366 px (lightest on usage)"), (1920, "1920 px (balanced)"), (0, "Full resolution (sharpest)")]
POINTERS = [("theme", "Theme default"), ("hand", "Pixel hand"), ("arrow", "Pixel arrow"), ("ring", "Ring"), ("dot", "Dot"),
            ("glass", "Liquid glass lens"), ("glasshand", "Liquid glass hand")]
PACES = [("slow", "Slow"), ("normal", "Normal"), ("fast", "Fast")]
SHORTCUTS = os.path.expanduser("~/.config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom")


def combo_row(title, subtitle, section, key, options):
    row = Adw.ComboRow(title=title, subtitle=subtitle or "")
    row.set_model(Gtk.StringList.new([label for _, label in options]))
    values = [v for v, _ in options]
    current = settings.get(section, key)
    row.set_selected(values.index(current) if current in values else 0)
    row.connect("notify::selected", lambda r, _p: settings.set(section, key, values[r.get_selected()]))
    return row


def spin_row(title, subtitle, section, key, lo, hi, step, digits=0):
    adj = Gtk.Adjustment(value=settings.get(section, key), lower=lo, upper=hi, step_increment=step)
    row = Adw.SpinRow(title=title, subtitle=subtitle or "", adjustment=adj, digits=digits)
    as_int = isinstance(settings.DEFAULTS[section][key], int)
    row.connect("notify::value", lambda r, _p: settings.set(section, key, int(r.get_value()) if as_int
                                                             else round(r.get_value(), 2)))
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


class SettingsWindow(Adw.PreferencesWindow):
    def __init__(self, app, on_preview, on_reset):
        global _adw_ready
        if not _adw_ready:
            Adw.init()
            _adw_ready = True
        super().__init__(application=app, title="Flippy Settings", default_width=640, default_height=760)
        self.set_modal(False)  # Adw.PreferencesWindow is modal by default, which blocks the pointer editors
        self.set_search_enabled(False)
        self.add(self._appearance(on_preview))
        self.add(self._claude(on_reset))
        self.add(self._timing(on_preview))
        self.add(self._hotkeys())
        self._listener = lambda s, k, v: s == "look" and self.picker_redraw()
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
        g.add(spin_row("Pointer size", None, "look", "pointer_size", 0.5, 2.0, 0.1, digits=1))
        g.add(spin_row("Text size", "Answer text, in px", "look", "text_size", 11, 24, 1))
        g.add(spin_row("Panel opacity", None, "look", "card_opacity", 0.5, 1.0, 0.02, digits=2))
        g.add(combo_row("Playback controls", "Clickable play/pause/step buttons on the answer panel", "look", "controls",
                        [("all", "On every theme"), ("players", "Only on Glass and Y2K Player")]))
        page.add(g)

        g = Adw.PreferencesGroup()
        g.add(button_row("Preview", "Plays a short fake walkthrough on your screen", "Preview", on_preview, "suggested-action"))
        page.add(g)
        return page

    def _claude(self, on_reset):
        page = Adw.PreferencesPage(title="Claude", icon_name="dialog-information-symbolic")
        g = Adw.PreferencesGroup(title="Model", description="Changes apply from your next question (it starts a fresh session).")
        g.add(combo_row("Model", None, "claude", "model", MODELS))
        g.add(combo_row("Effort", "Higher thinks more carefully but answers slower", "claude", "effort", EFFORTS))
        g.add(combo_row("Screenshot detail", "Sharper helps with tiny icons but uses more of your plan",
                        "claude", "image", IMAGES))
        page.add(g)
        g = Adw.PreferencesGroup(title="Session")
        g.add(button_row("Start fresh session", "Forget the conversation so far", "Reset", on_reset))
        page.add(g)
        return page

    def _timing(self, on_preview):
        page = Adw.PreferencesPage(title="Timing", icon_name="preferences-system-time-symbolic")
        g = Adw.PreferencesGroup(title="Answers")
        g.add(spin_row("Stay up for", "Seconds after the answer finishes", "timing", "show_seconds", 3, 60, 1))
        g.add(spin_row("Longest stay", "Cap for long answers, in seconds", "timing", "max_show_seconds", 5, 120, 1))
        page.add(g)
        g = Adw.PreferencesGroup(title="Walkthroughs")
        g.add(combo_row("Step pace", "How long each pointed step stays", "timing", "step_pace", PACES))
        g.add(spin_row("Playback speed", "Also on the Glass/Y2K players' slider", "timing", "speed", 0.5, 2.0, 0.05, digits=2))
        g.add(spin_row("Glide time", "Seconds for the pointer to travel between steps", "timing", "glide_seconds",
                       0.2, 2.0, 0.1, digits=1))
        g.add(button_row("Try it", None, "Preview", on_preview))
        page.add(g)
        return page

    def _hotkeys(self):
        page = Adw.PreferencesPage(title="Hotkeys", icon_name="input-keyboard-symbolic")
        g = Adw.PreferencesGroup(title="Shortcuts", description="Set in COSMIC Settings → Keyboard → Custom shortcuts.")
        found = False
        for keys, cmd in _flippy_shortcuts():
            found = True
            action = {"": "Ask a question", "draw": "Draw mode (circle something)"}.get(cmd, cmd)
            row = Adw.ActionRow(title=action, subtitle=f"flippy-ask {cmd}".strip())
            row.add_suffix(Gtk.ShortcutLabel(accelerator=keys, valign=Gtk.Align.CENTER))
            g.add(row)
        if not found:
            g.add(Adw.ActionRow(title="No Flippy shortcuts found",
                                subtitle="Add one that runs ~/.local/bin/flippy-ask"))
        g.add(button_row("Change shortcuts", None, "Open COSMIC Settings",
                         lambda: subprocess.Popen(["cosmic-settings", "keyboard"])))
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


def _flippy_shortcuts():
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
