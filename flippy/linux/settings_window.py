"""Flippy settings window (GTK). Every change is saved and applied immediately.

The same pages and look as flippy/mac/settings_window.py: outlined buttons along the top switch pages, and each
page is a plain list of grouped rows on black (flippy/linux/style.py), with libadwaita's preference rows
restyled. A normal window on purpose: on COSMIC, layer surfaces can't be closed safely (see daemon.py).
"""
import os
import re
import subprocess

import cairo
import gi

gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import pointer_editor, style  # noqa: E402
from .. import pointers, settings, themes, updates  # noqa: E402

_adw_ready = False

MODELS = settings.options('claude', 'model')
EFFORTS = settings.options('claude', 'effort')
IMAGES = settings.options('claude', 'image')
POINTERS = settings.options('look', 'pointer')
PACES = settings.options('timing', 'step_pace')
HELP_MODES = settings.options('help', 'mode')
SHORTCUTS = os.path.expanduser("~/.config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom")
WIDTH, HEIGHT = 640, 760
THUMB_W, THUMB_H = 288, 150

SAMPLE = themes.Card(text="The pointer glides here and the panel follows it.", header="Workspaces",
                     steps=["Launcher", "Workspaces"], step=1, progress=0.45, meta="OPUS · LOW", follow=True)


# ---- rows: title and muted subtitle on the left, an outlined control on the right (like the macOS Form)
def row(title, subtitle=None, control=None):
    r = Adw.ActionRow(title=GLib.markup_escape_text(title), subtitle=GLib.markup_escape_text(subtitle or ""))
    if control is not None:
        control.set_valign(Gtk.Align.CENTER)
        r.add_suffix(control)
    return r


def dropdown(options, current, fn, width=220):
    """options: [(value, label)]; fn(value) on change."""
    values = [v for v, _ in options]
    d = Gtk.DropDown.new_from_strings([label for _, label in options])
    d.set_size_request(width, -1)
    d.set_selected(values.index(current) if current in values else 0)
    d.values = values
    d.connect("notify::selected",
              lambda dd, _p: dd.get_selected() < len(dd.values) and fn(dd.values[dd.get_selected()]))
    return d


def combo_row(title, subtitle, section, key, options, width=220):
    return row(title, subtitle, dropdown(options, settings.get(section, key), lambda v: settings.set(section, key, v),
                                         width))


def slider(section, key, width=170):
    """A slider with its value beside it, like widgets.slider() on macOS. Saves while dragging."""
    spec = settings.SETTINGS[section, key]
    as_int = isinstance(settings.DEFAULTS[section][key], int)
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, spec.minimum, spec.maximum, spec.step)
    scale.set_value(settings.get(section, key))
    scale.set_digits(spec.digits)
    scale.set_draw_value(True)
    scale.set_value_pos(Gtk.PositionType.RIGHT)
    scale.set_size_request(width + 44, -1)

    def changed(s):
        v = round(round(s.get_value() / spec.step) * spec.step, 4)
        v = int(v) if as_int else round(v, spec.digits)
        if v != settings.get(section, key):
            settings.set(section, key, v)
    scale.connect("value-changed", changed)
    return scale


def slider_row(title, subtitle, section, key):
    return row(title, subtitle, slider(section, key))


def check(on, fn):
    """The square outlined checkbox."""
    c = Gtk.CheckButton(active=on)
    c.connect("toggled", lambda b: fn(b.get_active()))
    return c


def check_row(title, subtitle, section, key):
    c = check(settings.get(section, key), lambda on: settings.set(section, key, on))
    c.update_property([Gtk.AccessibleProperty.LABEL], [title])
    return row(title, subtitle, c)


def button_row(title, subtitle, label, callback):
    return row(title, subtitle, style.button(label, callback))


def buttons(*items):
    """A right-aligned set of outlined buttons."""
    box = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    for b in items:
        box.append(b)
    return box


def group(title=None, description=None):
    g = Adw.PreferencesGroup(title=GLib.markup_escape_text(title or ""))
    if description:  # an empty one still takes its line
        g.set_description(GLib.markup_escape_text(description))
    return g


def draw_thumb(cr, w, h, theme):
    """One theme's answer card on a sample background; the one in use has a bright, thicker outline."""
    g = cairo.LinearGradient(0, 0, w, h)
    g.add_color_stop_rgb(0, 0.33, 0.2, 0.3)
    g.add_color_stop_rgb(1, 0.13, 0.11, 0.24)
    cr.set_source(g)
    cr.paint()
    opts = {"text_size": 15, "card_opacity": settings.get("look", "card_opacity")}
    cw, ch = theme.size(SAMPLE, opts)
    k = min((w - 50) / cw, (h - 16) / ch, 1.0)
    cr.save()
    cr.translate(44, (h - ch * k) / 2)
    cr.scale(k, k)
    theme.draw(cr, 0, 0, cw, ch, SAMPLE, 1.2, opts)
    cr.restore()
    pointer = settings.get("look", "pointer")
    themes.draw_pointer(cr, theme, theme.pointer if pointer == "theme" else pointer, 22, 18, 1.0, 0.45, 10_000)
    selected = settings.get("look", "theme") == theme.key
    cr.set_source_rgb(*(style.TEXT if selected else style.OUTLINE))
    cr.set_line_width(4 if selected else 1)
    inset = 2 if selected else 0.5
    cr.rectangle(inset, inset, w - 2 * inset, h - 2 * inset)
    cr.stroke()


class ThemePicker(Gtk.Grid):
    """Clickable live thumbnails of each theme's answer card, two to a row."""

    def __init__(self):
        super().__init__(column_spacing=16, row_spacing=10, margin_top=4)
        self.areas = []
        for i, (key, theme) in enumerate(themes.THEMES.items()):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            area = Gtk.DrawingArea(content_width=THUMB_W, content_height=THUMB_H)
            area.set_draw_func(lambda _a, cr, w, h, t=theme: draw_thumb(cr, w, h, t))
            box.append(area)
            box.append(Gtk.Label(label=theme.name, css_classes=["small"]))
            btn = Gtk.Button(child=box, css_classes=["thumb"])
            btn.update_property([Gtk.AccessibleProperty.LABEL], [theme.name + " theme"])
            btn.connect("clicked", lambda *_, k=key: settings.set("look", "theme", k))
            self.areas.append(area)
            self.attach(btn, i % 2, i // 2, 1, 1)

    def redraw(self):
        for area in self.areas:
            area.queue_draw()


class SettingsWindow(Gtk.Window):
    PAGES = (("appearance", "Appearance"), ("models", "Models"), ("automation", "Automation"), ("timing", "Timing"),
             ("help", "Help"), ("hotkeys", "Hotkeys"))

    def __init__(self, app, on_preview, on_reset, command=lambda cmd: None, glass=False):
        """glass: the overlay draws real Liquid Glass, so its tint and reflections settings apply."""
        global _adw_ready
        if not _adw_ready:
            Adw.init()
            _adw_ready = True
        super().__init__(application=app, title="Flippy Settings", default_width=WIDTH, default_height=HEIGHT)
        style.apply(self)
        self.set_titlebar(style.headerbar("Flippy Settings"))
        self.command = command
        self.glass = glass
        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.NONE)
        build = {"appearance": lambda: self._appearance(on_preview), "models": lambda: self._claude(on_reset),
                 "automation": self._actions, "timing": lambda: self._timing(on_preview), "help": self._help,
                 "hotkeys": self._hotkeys}
        # pages switch with outlined buttons along the top that share their edges (each as wide as its title,
        # which Gtk.StackSwitcher doesn't do)
        tabs = Gtk.Box(halign=Gtk.Align.START, margin_start=24, margin_end=24, margin_top=14, margin_bottom=13)
        self.tabs = {}
        for name, title in self.PAGES:
            self.stack.add_titled(build[name](), name, title)
            tab = Gtk.ToggleButton(label=title, css_classes=["tab"], group=next(iter(self.tabs.values()), None))
            tab.connect("toggled", lambda b, n=name: b.get_active() and self.stack.set_visible_child_name(n))
            tabs.append(tab)
            self.tabs[name] = tab
        self.tabs["appearance"].set_active(True)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.append(tabs)
        root.append(style.rule())
        root.append(self.stack)
        self.set_child(root)
        self._listener = lambda s, k, v: ((s == "look" and self.picker_redraw())
                                        or (s == "help" and self._fill_apps())
                                        or (s == "act" and k == "allowed_apps" and self._fill_allowed_apps()))
        settings.on_change(self._listener)
        self.connect("close-request", lambda *_: settings.off_change(self._listener) or False)

    def show_page(self, name):
        self.tabs[name].set_active(True)

    # ---- pointer choices (built-ins + custom)
    def _pointer_options(self):
        return POINTERS + [(pointers.PREFIX + n, f"Custom: {n}") for n in pointers.names()]

    def _fill_pointer_choice(self):
        self._filling = True
        opts = self._pointer_options()
        self.pointer_choice.values = [v for v, _ in opts]
        self.pointer_choice.set_model(Gtk.StringList.new([label for _, label in opts]))
        cur = settings.get("look", "pointer")
        values = self.pointer_choice.values
        self.pointer_choice.set_selected(values.index(cur) if cur in values else 0)
        self._filling = False

    def _pointer_chosen(self, value):
        if not getattr(self, "_filling", False):
            settings.set("look", "pointer", value)
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
        self._fill_pointer_choice()
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
                self._fill_pointer_choice()
                self._update_custom_buttons()
                self.picker_redraw()
        dlg.connect("response", on_response)
        dlg.present()

    def picker_redraw(self):
        self.picker.redraw()

    # ---- pages
    @staticmethod
    def _page(*groups):
        """The groups, top to bottom with the macOS form's 24 px sides (Adw.PreferencesPage narrows and centers)."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["page"], margin_start=24, margin_end=24,
                      margin_top=18, margin_bottom=24)
        for g in groups:
            box.append(g)
        return Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=box)

    def _appearance(self, on_preview):
        theme = group("Theme", "Sets the answer panel, pointer, pen and question box together.")
        self.picker = ThemePicker()
        theme.add(self.picker)

        look = group("Pointer and panel")
        self.pointer_choice = dropdown([], None, self._pointer_chosen)
        self._fill_pointer_choice()
        look.add(row("Pointer", "Override the theme's pointer", self.pointer_choice))
        self.edit_btn = style.button("Edit…", self._edit_current)
        self.del_btn = style.button("Delete", self._delete_current)
        look.add(row("Custom pointers", "Import an image or draw pixel art",
                     buttons(style.button("Add image…", self._add_image), style.button("Draw…", self._draw_new),
                             self.edit_btn, self.del_btn)))
        self._update_custom_buttons()
        look.add(slider_row("Pointer size", None, "look", "pointer_size"))
        look.add(slider_row("Text size", "Answer text, in px", "look", "text_size"))
        look.add(slider_row("Panel opacity", None, "look", "card_opacity"))
        if self.glass:
            look.add(slider_row("Glass tint", "How tinted Liquid Glass is (Glass, Media Player, the ask box)",
                                "look", "glass_tint"))
            look.add(combo_row("Tint color", None, "look", "glass_color", settings.options("look", "glass_color")))
        look.add(combo_row("Playback controls", "Clickable play/pause/step buttons on the answer panel", "look",
                           "controls", settings.options("look", "controls")))
        if self.glass:
            look.add(combo_row("Media Player reflections", "Windows Media Player gloss bars on its Liquid Glass, "
                               "or plain glass", "look", "player_shine", settings.options("look", "player_shine")))
        look.add(button_row("Preview", "Plays a short fake walkthrough on your screen", "Preview", on_preview))
        return self._page(theme, look)

    def _claude(self, on_reset):
        connection = group("Connection", "Uses your signed-in subscription. Changing the connection starts a fresh "
                                         "session.")
        connection.add(combo_row("Provider", None, "provider", "mode", settings.options("provider", "mode")))
        claude = group("Claude", "Model and effort apply when Claude is selected.")
        claude.add(combo_row("Model", None, "claude", "model", MODELS))
        claude.add(combo_row("Effort", "Higher thinks more carefully but answers slower", "claude", "effort", EFFORTS))
        claude.add(combo_row("Screenshot detail", "Sharper helps with tiny icons but uses more of your plan",
                             "claude", "image", IMAGES))
        codex = group("Codex / ChatGPT", "Uses the Codex sign-in. Model and effort apply when Codex is selected.")
        model = Gtk.Entry(text=settings.get("codex", "model"), width_chars=22)
        model.set_size_request(220, -1)
        model.connect("activate", self._codex_model_changed)
        codex.add(row("Model", "default uses the account model; press Enter to apply", model))
        codex.add(combo_row("Effort", None, "codex", "effort", settings.options("codex", "effort")))
        session = group("Session")
        session.add(button_row("Start fresh session", "Forget the conversation so far", "Reset", on_reset))
        upd = group("Updates", f"You have Flippy {updates.current_version()}.")
        upd.add(check_row("Check for updates daily", "When a new version is out, Flippy offers to install it",
                          "updates", "check"))
        upd.add(button_row("Check now", None, "Check", lambda: self.command("update")))
        return self._page(connection, claude, codex, session, upd)

    def _codex_model_changed(self, entry):
        try:
            settings.set("codex", "model", entry.get_text().strip())
        except ValueError:
            entry.set_text(settings.get("codex", "model"))

    def _actions(self):
        tasks = group("Desktop tasks", "Applies only to /act. Questions and walkthroughs remain tool-free.")
        tasks.add(combo_row("Approval", None, "act", "mode", settings.options("act", "mode")))
        tasks.add(row("Ask once per app", "Approve an app when a task first needs it; remembered apps can be removed "
                                          "below."))
        tasks.add(row("Act automatically", "Allows desktop input without an approval card. Stop the task to halt "
                                           "further input."))
        tasks.add(row("Ask before every input", "Shows each proposed click, text entry, key, scroll or drag for "
                                                "approval."))
        strict, automatic = settings.ACT_LIMITS["every_input"], settings.ACT_LIMITS["auto"]
        tasks.add(row("Task bounds", f"Every input: {strict.max_actions} inputs, {strict.timeout_seconds // 60} "
                                     f"minutes. Other modes: {automatic.max_actions} inputs, "
                                     f"{automatic.timeout_seconds // 60} minutes."))
        self.allowed_group = group("Remembered apps", "Removing an app makes the next task ask again in Ask once per "
                                                      "app mode.")
        self.allowed_rows = []
        self._fill_allowed_apps()
        return self._page(tasks, self.allowed_group)

    def _fill_allowed_apps(self):
        for r in self.allowed_rows:
            self.allowed_group.remove(r)
        self.allowed_rows = []
        apps = settings.get("act", "allowed_apps")
        for app in apps:
            r = row(app, None, style.button("Remove", lambda app=app: settings.remove_allowed_app(app)))
            self.allowed_group.add(r)
            self.allowed_rows.append(r)
        if not apps:
            r = row("None yet")
            self.allowed_group.add(r)
            self.allowed_rows.append(r)

    def _timing(self, on_preview):
        answers = group("Answers")
        answers.add(slider_row("Stay up for", "Seconds after the answer finishes", "timing", "show_seconds"))
        answers.add(slider_row("Longest stay", "Cap for long answers, in seconds", "timing", "max_show_seconds"))
        walk = group("Walkthroughs")
        walk.add(combo_row("Step pace", "How long each pointed step stays", "timing", "step_pace", PACES))
        walk.add(slider_row("Playback speed", "Also on the Media Player/Y2K players' slider", "timing", "speed"))
        walk.add(slider_row("Glide time", "Seconds for the pointer to travel between steps", "timing",
                            "glide_seconds"))
        walk.add(check_row("Wait for my clicks", "Tutorials pause on steps you have to do until you click the thing",
                           "timing", "wait_for_clicks"))
        walk.add(button_row("Try it", None, "Preview", on_preview))
        return self._page(answers, walk)

    def _help(self):
        mode = group("Help mode", "Flippy watches only the apps below, with simple local rules, and asks nothing of "
                                  "Claude until you press Help or Show me.")
        mode.add(combo_row("When I'm learning an app", None, "help", "mode", HELP_MODES))
        self.apps_group = group("Watched apps", "Add the app in front from Flippy's panel icon → Watch <app>.")
        self.muted_group = group("Don't ask in", "Apps where you chose “Don't ask in <app>”.")
        self.app_rows = []
        self._fill_apps()
        return self._page(mode, self.apps_group, self.muted_group)

    def _fill_apps(self):
        for g, r in self.app_rows:
            g.remove(r)
        self.app_rows = []
        from .sensors import app_name
        for g, key, empty in ((self.apps_group, "apps", "None yet"), (self.muted_group, "muted", "None")):
            ids = sorted(settings.get_list("help", key))
            for app in ids:
                r = row(app_name(app), app, style.button(
                    "Remove", lambda k=key, a=app: settings.set_list("help", k, settings.get_list("help", k) - {a})))
                g.add(r)
                self.app_rows.append((g, r))
            if not ids:
                r = row(empty)
                g.add(r)
                self.app_rows.append((g, r))

    def _hotkeys(self):
        keys = group("Shortcuts", "COSMIC runs these from any app. Change them in COSMIC Settings → Keyboard → "
                                  "Custom shortcuts.")
        found = False
        for accel, cmd in flippy_shortcuts():
            found = True
            action = {"": "Ask about the screen", "draw": "Circle something, then ask",
                      "pause-toggle": "Pause / resume a walkthrough", "video": "Check a video edit"}.get(cmd, cmd)
            keys.add(row(action, f"flippy-ask {cmd}".strip(), style.keycaps(pretty_accel(accel).split("+"))))
        if not found:
            keys.add(row("No Flippy shortcuts found", "Add one that runs ~/.local/bin/flippy-ask, or let Setup add "
                                                      "them"))
        keys.add(button_row("Change shortcuts", None, "Open COSMIC Settings",
                            lambda: subprocess.Popen(["cosmic-settings", "keyboard"])))
        scripts = group("Scripts", "flippy-ask type / key / tap send real keystrokes (used for recording demos). "
                                   "Off by default: when on, any program running as you can make Flippy type. This "
                                   "is separate from /act approvals.")
        scripts.add(check_row("Let scripts type", None, "automation", "clicks"))
        box = group("In the question box")
        for cmd, what in (("/new", "Start a fresh session"), ("/settings", "Open this window"), ("Esc", "Close")):
            box.add(row(what, cmd))
        config = group("Config file")
        config.add(button_row(settings.PATH.replace(os.path.expanduser("~"), "~"), "Edit by hand if you like", "Open",
                              lambda: subprocess.Popen(["xdg-open", settings.PATH])))
        return self._page(keys, scripts, box, config)


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
