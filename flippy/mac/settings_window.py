"""Flippy settings window (AppKit). Every change is saved and applied immediately.

Same pages as the GTK window (flippy/linux/settings_window.py): Appearance,
Claude, Timing, Hotkeys. The hotkeys are recorded here, since macOS has no
system-wide custom shortcut list to point at.
"""
import os
import subprocess

import cairo
from AppKit import (NSAlert, NSAlertFirstButtonReturn, NSApp, NSBackingStoreBuffered, NSEvent,
                    NSEventMaskKeyDown, NSScrollView, NSTabView, NSTabViewItem, NSWindow,
                    NSWindowStyleMaskClosable, NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskTitled)
from Foundation import NSMakeRect, NSObject

from .. import pointers, settings, themes
from . import hotkeys, pointer_editor
from .cairoview import cairo_view
from .system import appearance
from .widgets import Form, button, checkbox, label, popup, set_popup, slider

MODELS = [("default", "Account default"), ("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku")]
EFFORTS = [("low", "Low (fastest)"), ("medium", "Medium"), ("high", "High"), ("max", "Max (slowest)")]
IMAGES = [(1366, "1366 px (lightest on usage)"), (1920, "1920 px (balanced)"), (0, "Full resolution (sharpest)")]
POINTERS = [("theme", "Theme default"), ("hand", "Pixel hand"), ("arrow", "Pixel arrow"), ("ring", "Ring"), ("dot", "Dot"),
            ("glass", "Liquid glass lens"), ("glasshand", "Liquid glass hand")]
PACES = [("slow", "Slow"), ("normal", "Normal"), ("fast", "Fast")]
CONTROLS = [("all", "On every theme"), ("players", "Only Glass and Y2K")]
SHINES = [("wmp", "WMP gloss"), ("none", "Plain glass")]
WIDTH, HEIGHT = 640, 720
THUMB_W, THUMB_H = 280, 150

SAMPLE = themes.Card(text="The pointer glides here and the panel follows it.", header="Wi-Fi",
                     steps=["Control Center", "Wi-Fi"], step=1, progress=0.45, meta="OPUS · LOW", follow=True)


def draw_thumb(cr, w, h, theme):
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
    style = settings.get("look", "pointer")
    themes.draw_pointer(cr, theme, theme.pointer if style == "theme" else style, 22, 18, 1.0, 0.45, 10_000)
    if settings.get("look", "theme") == theme.key:  # selected: accent ring
        cr.set_source_rgb(*appearance()[1])
        cr.set_line_width(4)
        cr.rectangle(2, 2, w - 4, h - 4)
        cr.stroke()


class WindowDelegate(NSObject):
    def windowWillClose_(self, note):
        self.on_close()


class KeyRecorder:
    """A button that shows a hotkey and, once clicked, records the next key combo typed."""

    def __init__(self, name, keep):
        self.name = name
        self.monitor = None
        self.btn = button(self._title(), self.toggle, keep)
        self.btn.setFrameSize_((170, self.btn.frame().size.height))

    def _title(self):
        return hotkeys.pretty(settings.get("keys", self.name))

    def toggle(self):
        if self.monitor:
            self.stop()
            return
        self.btn.setTitle_("Type a shortcut…")
        self.monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyDown, self._key)

    def _key(self, event):
        code, flags = event.keyCode(), event.modifierFlags()
        if code == 53 and not flags & 0x1E0000:  # bare Esc: cancel
            self.stop()
            return None
        mods = [n for bit, n in ((1 << 18, "ctrl"), (1 << 19, "option"), (1 << 17, "shift"), (1 << 20, "cmd"))
                if flags & bit]
        key = next((k for k, c in hotkeys.KEYS.items() if c == code), None)
        if key and mods:
            settings.set("keys", self.name, "+".join(mods + [key]))
            self.stop()
        else:
            self.btn.setTitle_("Needs ⌘, ⌃ or ⌥ + a key")
        return None  # swallow it

    def stop(self):
        if self.monitor:
            NSEvent.removeMonitor_(self.monitor)
            self.monitor = None
        self.btn.setTitle_(self._title())


class SettingsWindow:
    def __init__(self, on_preview, on_reset, on_close):
        self.keep = []
        self.thumbs = []
        self.recorders = []
        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, HEIGHT),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable,
            NSBackingStoreBuffered, False)
        self.win.setTitle_("Flippy Settings")
        self.win.setReleasedWhenClosed_(False)
        self.win.center()
        tabs = NSTabView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, HEIGHT))
        for title, form in (("Appearance", self._appearance(on_preview)), ("Claude", self._claude(on_reset)),
                            ("Timing", self._timing(on_preview)), ("Hotkeys", self._hotkeys())):
            item = NSTabViewItem.alloc().initWithIdentifier_(title)
            item.setLabel_(title)
            scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH - 20, HEIGHT - 60))
            scroll.setHasVerticalScroller_(True)
            scroll.setDrawsBackground_(False)
            scroll.setDocumentView_(form.finish())
            item.setView_(scroll)
            tabs.addTabViewItem_(item)
        self.win.setContentView_(tabs)

        self._listener = lambda s, k, v: self._changed(s, k)
        settings.on_change(self._listener)
        self.delegate = WindowDelegate.alloc().init()

        def closed():
            settings.off_change(self._listener)
            for r in self.recorders:
                r.stop()
            on_close()
        self.delegate.on_close = closed
        self.win.setDelegate_(self.delegate)

    def present(self):
        NSApp.activateIgnoringOtherApps_(True)  # a normal window: it needs the keyboard
        self.win.makeKeyAndOrderFront_(None)

    def _changed(self, section, key):
        if section == "look":
            for t in self.thumbs:
                t.setNeedsDisplay_(True)
        if section == "keys":
            for r in self.recorders:
                r.stop()

    # ---- pointer choices (built-ins + custom)
    def _pointer_options(self):
        return POINTERS + [(pointers.PREFIX + n, f"Custom: {n}") for n in pointers.names()]

    def _current_custom(self):
        cur = settings.get("look", "pointer")
        return cur[len(pointers.PREFIX):] if cur.startswith(pointers.PREFIX) else None

    def _refresh_pointers(self):
        set_popup(self.pointer_popup, self._pointer_options(), settings.get("look", "pointer"))
        on = self._current_custom() is not None
        self.edit_btn.setEnabled_(on)
        self.del_btn.setEnabled_(on)

    def _pointer_chosen(self, value):
        settings.set("look", "pointer", value)
        self._refresh_pointers()

    def _pointer_saved(self, name):
        settings.set("look", "pointer", pointers.PREFIX + name)
        self._refresh_pointers()

    def _delete_current(self):
        name = self._current_custom()
        if not name:
            return
        alert = NSAlert.alloc().init()
        alert.setMessageText_(f"Delete “{name}”?")
        alert.setInformativeText_("This can't be undone.")
        alert.addButtonWithTitle_("Delete")
        alert.addButtonWithTitle_("Cancel")
        alert.buttons()[0].setHasDestructiveAction_(True)
        if alert.runModal() == NSAlertFirstButtonReturn:
            settings.set("look", "pointer", "theme")
            pointers.delete(name)
            self._refresh_pointers()

    # ---- pages
    def _setting_popup(self, form, section, key, options, width=220):
        return popup(options, settings.get(section, key), lambda v: settings.set(section, key, v), form.keep, width)

    def _setting_slider(self, form, section, key, lo, hi, step, digits=0):
        return slider(lo, hi, step, settings.get(section, key), lambda v: settings.set(section, key, v),
                      form.keep, digits)

    def _appearance(self, on_preview):
        f = Form(WIDTH - 40)
        self.keep.append(f)
        f.group("Theme", "Sets the answer panel, pointer, pen and question box together.")
        for i, theme in enumerate(themes.THEMES.values()):
            col, x = i % 2, f.pad + (i % 2) * (THUMB_W + 16)
            if col == 0 and i:
                f.y += THUMB_H + 30
            v = cairo_view(NSMakeRect(0, 0, THUMB_W, THUMB_H), lambda cr, w, h, t=theme: draw_thumb(cr, w, h, t),
                           on_press=lambda x, y, right, k=theme.key: settings.set("look", "theme", k))
            self.thumbs.append(v)
            f._place(v, x, f.y)
            lab = label(theme.name, 12)
            f._place(lab, x + (THUMB_W - lab.frame().size.width) / 2, f.y + THUMB_H + 4)
        f.y += THUMB_H + 30

        f.group("Pointer and panel")
        self.pointer_popup = f.row("Pointer", "Override the theme's pointer",
                                   popup(self._pointer_options(), settings.get("look", "pointer"),
                                         self._pointer_chosen, f.keep))
        self.edit_btn = button("Edit…", lambda: (n := self._current_custom()) and pointer_editor.edit(self._pointer_saved, n), f.keep)
        self.del_btn = button("Delete", self._delete_current, f.keep)
        f.row("Custom pointers", "Import an image or draw pixel art")
        f.buttons(button("Add image…", lambda: pointer_editor.import_image(self._pointer_saved), f.keep),
                  button("Draw…", lambda: pointer_editor.PixelEditor(self._pointer_saved).present(), f.keep),
                  self.edit_btn, self.del_btn)
        self._refresh_pointers()
        f.row("Pointer size", None, self._setting_slider(f, "look", "pointer_size", 0.5, 2.0, 0.1, digits=1))
        f.row("Text size", "Answer text, in px", self._setting_slider(f, "look", "text_size", 11, 24, 1))
        f.row("Panel opacity", None, self._setting_slider(f, "look", "card_opacity", 0.5, 1.0, 0.02, digits=2))
        f.row("Playback controls", "Clickable play/pause/step buttons on the answer panel",
              self._setting_popup(f, "look", "controls", CONTROLS))
        f.row("Glass reflections", "Glass theme: Windows Media Player gloss bars, or plain Liquid Glass",
              self._setting_popup(f, "look", "glass_shine", SHINES))
        f.y += 6
        f.row("Preview", "Plays a short fake walkthrough on your screen", button("Preview", on_preview, f.keep, primary=True))
        return f

    def _claude(self, on_reset):
        f = Form(WIDTH - 40)
        self.keep.append(f)
        f.group("Model", "Changes apply from your next question (it starts a fresh session).")
        f.row("Model", None, self._setting_popup(f, "claude", "model", MODELS))
        f.row("Effort", "Higher thinks more carefully but answers slower", self._setting_popup(f, "claude", "effort", EFFORTS))
        f.row("Screenshot detail", "Sharper helps with tiny icons but uses more of your plan",
              self._setting_popup(f, "claude", "image", IMAGES))
        f.group("Session")
        f.row("Start fresh session", "Forget the conversation so far", button("Reset", on_reset, f.keep))
        return f

    def _timing(self, on_preview):
        f = Form(WIDTH - 40)
        self.keep.append(f)
        f.group("Answers")
        f.row("Stay up for", "Seconds after the answer finishes", self._setting_slider(f, "timing", "show_seconds", 3, 60, 1))
        f.row("Longest stay", "Cap for long answers, in seconds",
              self._setting_slider(f, "timing", "max_show_seconds", 5, 120, 1))
        f.group("Walkthroughs")
        f.row("Step pace", "How long each pointed step stays", self._setting_popup(f, "timing", "step_pace", PACES))
        f.row("Playback speed", "Also on the Glass/Y2K players' slider",
              self._setting_slider(f, "timing", "speed", 0.5, 2.0, 0.05, digits=2))
        f.row("Glide time", "Seconds for the pointer to travel between steps",
              self._setting_slider(f, "timing", "glide_seconds", 0.2, 2.0, 0.1, digits=1))
        f.row("Wait for my clicks", "Tutorials pause on steps you have to do until you click the thing",
              checkbox("", settings.get("timing", "wait_for_clicks"),
                       lambda on: settings.set("timing", "wait_for_clicks", on), f.keep))
        f.row("Try it", None, button("Preview", on_preview, f.keep))
        return f

    def _hotkeys(self):
        f = Form(WIDTH - 40)
        self.keep.append(f)
        f.group("Shortcuts", "Work from any app. Click one, then press the new combination (Esc cancels).")
        for name, what in (("ask", "Ask about the screen"), ("draw", "Circle something, then ask")):
            rec = KeyRecorder(name, f.keep)
            self.recorders.append(rec)
            f.row(what, None, rec.btn)
        f.group("Automation", "Lets scripts click on screen with flippy-ask click (used for recording demos). "
                              "Off by default: when on, any program running as you can make Flippy click. "
                              "Claude's answers never click. Also needs the Accessibility permission.")
        f.row("Let scripts click", None, checkbox("", settings.get("automation", "clicks"),
                                                  lambda on: settings.set("automation", "clicks", on), f.keep))
        f.group("In the question box")
        for cmd, what in (("/new", "Start a fresh session"), ("/settings", "Open this window"), ("Esc", "Close")):
            f.row(what, cmd)
        f.group("Config file")
        f.row(settings.PATH.replace(os.path.expanduser("~"), "~"), "Edit by hand if you like",
              button("Open", lambda: subprocess.Popen(["open", "-t", settings.PATH]), f.keep))
        return f
