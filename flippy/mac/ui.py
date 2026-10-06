"""macOS windows: a click-through overlay panel, the question box, screenshots, hotkeys, menu bar icon.

The overlay is a borderless, non-activating NSPanel above everything (menu bar
included) on the main display. The shared painting in flippy/overlay.py draws
into a cairo recording surface; only the painted area is rasterized at the
display's backing scale and blitted, so a mostly empty full-screen overlay
stays cheap. The panel ignores the mouse except over the card's controls
(checked every frame) and in draw mode.

Neither panel activates Flippy, so the app you were in stays frontmost and
gets the keyboard back as soon as the question box closes.
"""
import math
import os
import json
import socket
import subprocess
import tempfile
import threading
import time

import AppKit
import objc
import Quartz
from AppKit import (NSApp, NSApplication, NSApplicationActivationPolicyAccessory, NSBackingStoreBuffered,
                    NSColor, NSCursor, NSEvent, NSFont, NSFontAttributeName, NSForegroundColorAttributeName,
                    NSImage, NSMenu, NSMenuItem, NSPanel, NSScreen, NSScreenSaverWindowLevel,
                    NSStatusBar, NSTextField, NSTrackingActiveAlways, NSTrackingArea, NSTrackingCursorUpdate,
                    NSTrackingInVisibleRect, NSTrackingMouseMoved, NSVariableStatusItemLength, NSView,
                    NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorFullScreenAuxiliary,
                    NSWindowCollectionBehaviorIgnoresCycle, NSWindowCollectionBehaviorStationary,
                    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel, NSFloatingWindowLevel)
from Foundation import NSAttributedString, NSMakeRect, NSObject
from PyObjCTools import AppHelper
from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess

from .. import loop, settings, themes
from ..overlay import OverlayBase
from . import hotkeys, sensors, statusicon
from .nudge import Nudge
from .cairoview import blit
from .widgets import FlippedView

GLASS = hasattr(AppKit, "NSGlassEffectView")  # macOS 26+
# The Media Player theme's Liquid Glass, per surface (question box, its text field, answer card), 0-1:
# FROST is how milky (white) it is, SMOKE how dark. Both low = clear glass.
FROST = {"box": 0.10, "field": 0.30, "card": 0.03}
SMOKE = {"box": 0.25, "field": 0.40, "card": 0.25}


LENS = {"frost": 0.04, "smoke": 0.06}  # the glass pointer: nearly clear


def glass_color(frost, smoke):
    """Frost over smoke as one tint: white at `frost` on top of black at `smoke`."""
    a = frost + smoke * (1 - frost)
    return NSColor.colorWithWhite_alpha_(frost / a if a else 0, a)


def glass_tint(part):
    return glass_color(FROST[part], SMOKE[part])


def _glass_view(radius, tint):
    v = AppKit.NSGlassEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
    v.setStyle_(AppKit.NSGlassEffectViewStyleClear)
    v.setTintColor_(tint)
    v.setCornerRadius_(radius)
    v.setHidden_(True)
    return v
PLATFORM = None             # the running Platform (for windows that need it, like setup's Restart)
ESC_HOTKEY = 4              # hotkey id for Esc while drawing (1-2: ask/draw)
HIDE_SETTLE_MS = 150        # let the window server drop the question box before the screenshot
FRAME_MS = 16


def _rgba(r, g, b, a=1.0):
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, a)


def _hex(h, a=1.0):
    h = h.lstrip("#")
    return _rgba(*(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)), a)


def main_screen():
    return NSScreen.screens()[0]  # the one with the menu bar; single display for now


class KeyPanel(NSPanel):
    """A borderless panel that can still take the keyboard (without activating the app)."""

    def canBecomeKeyWindow(self):
        return True


# --------------------------------------------------------------------------- overlay

class OverlayView(NSView):
    def isFlipped(self):
        return True

    def acceptsFirstMouse_(self, event):
        return True

    def drawRect_(self, rect):
        self.owner.render(self)

    def updateTrackingAreas(self):
        objc.super(OverlayView, self).updateTrackingAreas()
        if not getattr(self, "tracking", None):
            opts = NSTrackingActiveAlways | NSTrackingInVisibleRect | NSTrackingCursorUpdate | NSTrackingMouseMoved
            self.tracking = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(self.bounds(), opts, self, None)
            self.addTrackingArea_(self.tracking)

    @objc.python_method
    def _pt(self, event):
        p = self.convertPoint_fromView_(event.locationInWindow(), None)
        return p.x, p.y

    def mouseDown_(self, event):
        self.owner.press(*self._pt(event))

    def mouseDragged_(self, event):
        self.owner.motion(*self._pt(event))

    def mouseUp_(self, event):
        self.owner.release()

    def rightMouseDown_(self, event):
        self.owner.right_click()

    def cursorUpdate_(self, event):
        self.owner.update_cursor()

    def mouseMoved_(self, event):
        self.owner.update_cursor()


def _show(view, on):
    if view.isHidden() == on:
        view.setHidden_(not on)


class Overlay(OverlayBase):
    has_backdrop = GLASS

    def __init__(self):
        super().__init__()
        frame = main_screen().frame()
        self.panel = p = KeyPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel, NSBackingStoreBuffered, False)
        p.setLevel_(NSScreenSaverWindowLevel)  # above the menu bar, so we can point at it
        p.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
                                 | NSWindowCollectionBehaviorFullScreenAuxiliary | NSWindowCollectionBehaviorIgnoresCycle)
        p.setOpaque_(False)
        p.setBackgroundColor_(NSColor.clearColor())
        p.setHasShadow_(False)
        p.setHidesOnDeactivate_(False)
        p.setIgnoresMouseEvents_(True)
        p.setReleasedWhenClosed_(False)
        bounds = NSMakeRect(0, 0, frame.size.width, frame.size.height)
        root = FlippedView.alloc().initWithFrame_(bounds)
        self.glass = self.lens = self.hand = None
        self.glass_theme = None
        if GLASS:  # Liquid Glass behind the card (Theme.backdrop) and the glass pointer; cairo paints on top
            self.glass = _glass_view(20, glass_tint("card"))
            self.lens = _glass_view(20, glass_color(LENS["frost"], LENS["smoke"]))
            root.addSubview_(self.glass)
            root.addSubview_(self.lens)
            # the glass hand: rounded pieces in a container, which fuses nearby glass into one shape
            self.hand = AppKit.NSGlassEffectContainerView.alloc().initWithFrame_(bounds)
            self.hand.setSpacing_(6)
            hand_view = FlippedView.alloc().initWithFrame_(bounds)
            self.hand_pieces = [_glass_view(4, glass_color(LENS["frost"], LENS["smoke"])) for _ in themes.GLASS_HAND]
            for piece in self.hand_pieces:
                hand_view.addSubview_(piece)
            self.hand.setContentView_(hand_view)
            self.hand.setHidden_(True)
            root.addSubview_(self.hand)
        self.view = OverlayView.alloc().initWithFrame_(bounds)
        self.view.owner = self
        root.addSubview_(self.view)
        p.setContentView_(root)
        p.orderFrontRegardless()
        self.tick_id = 0
        self.ignoring = True

    def size(self):
        b = self.view.bounds()
        return b.size.width, b.size.height

    def render(self, view):
        w, h = self.size()
        blit(lambda cr: self.paint(cr, w, h), w, h, self.panel.backingScaleFactor(), clip_to_ink=True)

    # --- hooks ---
    def queue_draw(self):
        self._place_glass()
        self.view.setNeedsDisplay_(True)

    def _place_glass(self):
        """Keep the glass exactly under the card and the pointer lens (both move every frame)."""
        if self.glass is None:
            return
        lay = self.card_layout(*self.size())
        if lay and lay[1]["backdrop"]:
            theme = self.theme
            if theme is not self.glass_theme:  # per-theme tint (Glass uses FROST/SMOKE["card"])
                self.glass_theme = theme
                bd = theme.backdrop
                self.glass.setTintColor_(glass_color(bd["frost"], bd["smoke"]) if "frost" in bd else glass_tint("card"))
                self.glass.setCornerRadius_(bd["radius"])
            self.glass.setFrame_(NSMakeRect(*lay[0]))
            _show(self.glass, True)
        else:
            _show(self.glass, False)
        pieces = self.pointer_hand(self.size()[1])
        if pieces:
            for view, (px, py, w, h, r, rot) in zip(self.hand_pieces, pieces):
                view.setFrameCenterRotation_(0)
                view.setFrame_(NSMakeRect(px, py, w, h))
                view.setCornerRadius_(r)
                view.setFrameCenterRotation_(rot)  # in a flipped parent this turns the same way as cairo
                _show(view, True)
        _show(self.hand, bool(pieces))
        lens = self.pointer_lens()
        if lens:
            cx, cy, r = lens
            self.lens.setFrame_(NSMakeRect(cx - r, cy - r, 2 * r, 2 * r))
            self.lens.setCornerRadius_(r)
            _show(self.lens, True)
        else:
            _show(self.lens, False)

    def set_opacity(self, a):
        self.panel.setAlphaValue_(a)

    def start_ticking(self):
        self.tick_id = loop.timeout_add(FRAME_MS, lambda: self.tick() or True)

    def stop_ticking(self):
        if self.tick_id:
            loop.source_remove(self.tick_id)
            self.tick_id = 0

    def set_drawing_input(self, on):
        self._set_ignoring(not on)
        self.update_cursor()
        # the overlay never takes the keyboard, so Esc is a global hotkey, only while drawing
        if on:
            err = hotkeys.register(ESC_HOTKEY, "escape", lambda: self.on_draw_cancel())
            if err:
                print(f"flippy: Esc while drawing: {err}", flush=True)
        else:
            hotkeys.unregister(ESC_HOTKEY)

    def _mouse(self):
        """Mouse position in overlay (flipped, logical) coordinates."""
        p, f = NSEvent.mouseLocation(), self.panel.frame()
        return p.x - f.origin.x, f.origin.y + f.size.height - p.y

    def _over_control(self):
        x, y = self._mouse()
        return any(rx <= x <= rx + rw and ry <= y <= ry + rh for rx, ry, rw, rh in self.hits.values())

    def hits_changed(self):
        """Take clicks only while the mouse is over a control (or dragging a slider)."""
        if not self.drawing:
            self._set_ignoring(not (self.slider or (self.hits and self._over_control())))

    def _set_ignoring(self, ignore):
        if ignore != self.ignoring:
            self.ignoring = ignore
            self.panel.setIgnoresMouseEvents_(ignore)
            self.update_cursor()

    def update_cursor(self):
        if self.drawing:
            NSCursor.crosshairCursor().set()
        elif not self.ignoring:
            NSCursor.pointingHandCursor().set()
        else:
            NSCursor.arrowCursor().set()


# --------------------------------------------------------------------------- question box

def box_style(theme):
    """The question box's look per theme (the macOS counterpart of Theme.box_css)."""
    sys_font = (None, 16)
    st = {"bg": _rgba(24 / 255, 24 / 255, 28 / 255, 0.94), "border": _rgba(90 / 255, 160 / 255, 1, 0.55),
          "border_w": 1, "radius": 14, "fg": _hex("f2f2f2"), "font": sys_font, "field_bg": None,
          "field_border": None, "field_radius": 0, "hint": _rgba(1, 1, 1, 0.5), "hint_font": (None, 12)}
    if theme.key == "cosmic":
        st.update(bg=_rgba(*theme.bg, 0.96), border=_rgba(*theme.accent, 0.7), radius=theme.radius,
                  fg=_rgba(*theme.fg), hint=_rgba(*theme.fg, 0.5))
    elif theme.key == "terminal":
        green = (64 / 255, 1, 115 / 255)
        st.update(bg=_hex("030805"), border=_rgba(*green, 0.6), radius=0, fg=_rgba(*green), font=("Menlo", 16),
                  field_bg=_hex("000000"), field_border=_rgba(*green, 0.35), hint=_rgba(*green, 0.55),
                  hint_font=("Menlo", 12))
    elif theme.key == "y2k":
        st.update(bg=_hex("33363f"), border=_hex("9ca1b3"), border_w=2, radius=2, fg=_hex("00ff6a"),
                  font=(themes.PIXEL_FONT, 24), field_bg=_hex("000000"), field_border=_hex("0c0d12"),
                  hint=_hex("7dffa9"), hint_font=(themes.PIXEL_FONT, 16))
    elif theme.key == "mediaplayer" and GLASS:  # Liquid Glass box; the field is a frostier, smokier pane
        st.update(glass=True, bg=None, border=_rgba(1, 1, 1, 0.35), radius=theme.LIQUID_R, fg=_hex("ffffff"),
                  font=(None, 16), field_bg=glass_tint("field"), field_border=_rgba(1, 1, 1, 0.3),
                  field_radius=12, hint=_rgba(1, 1, 1, 0.9), hint_shadow=True)
    elif theme.key == "glass" and GLASS:  # same glass box, the lock screen's rounder corners
        st.update(glass=True, bg=None, border=_rgba(1, 1, 1, 0.3), radius=theme.R, fg=_hex("ffffff"),
                  font=(None, 16), field_bg=_rgba(1, 1, 1, 0.12), field_border=None,
                  field_radius=12, hint=_rgba(1, 1, 1, 0.75), hint_shadow=True)
    elif theme.key == "glass":  # (no Liquid Glass on this macOS)
        st.update(bg=_rgba(40 / 255, 40 / 255, 46 / 255, 0.85), border=_rgba(1, 1, 1, 0.3), radius=theme.R,
                  field_bg=_rgba(1, 1, 1, 0.12), field_radius=12)
    elif theme.key == "mediaplayer":
        st.update(bg=_rgba(40 / 255, 46 / 255, 48 / 255, 0.88), border=_rgba(0, 0, 0, 0.7), radius=9, fg=_hex("ffffff"),
                  font=(None, 15), field_bg=_rgba(0, 0, 0, 0.3), field_border=_rgba(0, 0, 0, 0.6), field_radius=12,
                  hint=_rgba(235 / 255, 238 / 255, 240 / 255, 0.7))
    return st


def _font(spec):
    name, size = spec
    return (NSFont.fontWithName_size_(name, size) if name else None) or NSFont.systemFontOfSize_(size)


def _layer(view, bg, border=None, border_w=1, radius=0):
    view.setWantsLayer_(True)
    layer = view.layer()
    layer.setBackgroundColor_(bg.CGColor() if bg else None)
    if border:
        layer.setBorderColor_(border.CGColor())
        layer.setBorderWidth_(border_w)
    layer.setCornerRadius_(radius)


class BoxDelegate(NSObject, protocols=[objc.protocolNamed("NSTextFieldDelegate")]):
    def control_textView_doCommandBySelector_(self, control, text_view, sel):
        sel = sel.decode() if isinstance(sel, bytes) else str(sel)
        if sel == "insertNewline:":
            self.box.on_submit(str(control.stringValue()).strip())
            return True
        if sel == "cancelOperation:":
            self.box.on_cancel()
            return True
        return False


class InputBox:
    WIDTH = 560
    PAD_X, PAD_Y = 16, 12

    def __init__(self, on_submit, on_cancel):
        self.on_submit = on_submit
        self.on_cancel = on_cancel
        self.panel = None
        self.delegate = BoxDelegate.alloc().init()
        self.delegate.box = self

    @property
    def visible(self):
        return self.panel is not None

    def show(self):
        if self.panel:
            self.panel.makeKeyAndOrderFront_(None)
            return
        theme = themes.get(settings.get("look", "theme"))
        st = box_style(theme)
        font, hint_font = _font(st["font"]), _font(st["hint_font"])
        field_h = math.ceil(font.ascender() - font.descender() + font.leading()) + 12
        hint_h = math.ceil(hint_font.ascender() - hint_font.descender()) + 2
        w = self.WIDTH + 2 * self.PAD_X
        h = self.PAD_Y + field_h + 6 + hint_h + self.PAD_Y

        frame = main_screen().visibleFrame()
        x = frame.origin.x + (frame.size.width - w) / 2
        y = frame.origin.y + frame.size.height * 0.72 - h
        panel = KeyPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, w, h), NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, False)
        panel.setLevel_(NSFloatingWindowLevel)
        panel.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces
                                     | NSWindowCollectionBehaviorFullScreenAuxiliary)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setMovableByWindowBackground_(True)  # drag the box anywhere outside the text field
        panel.setReleasedWhenClosed_(False)
        panel.setBecomesKeyOnlyIfNeeded_(False)

        card = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        _layer(card, st["bg"], st["border"], st["border_w"], st["radius"])
        root = card
        if st.get("glass"):
            root = AppKit.NSGlassEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
            root.setStyle_(AppKit.NSGlassEffectViewStyleClear)
            root.setTintColor_(glass_tint("box"))
            root.setCornerRadius_(st["radius"])
            root.setContentView_(card)
            panel.setHasShadow_(False)  # the glass draws its own edge and depth
        field_box = NSView.alloc().initWithFrame_(NSMakeRect(self.PAD_X, h - self.PAD_Y - field_h, self.WIDTH, field_h))
        _layer(field_box, st["field_bg"], st["field_border"], 1, st["field_radius"])
        inset = 8 if st["field_bg"] else 0
        entry = NSTextField.alloc().initWithFrame_(NSMakeRect(inset, 6, self.WIDTH - 2 * inset, field_h - 12))
        entry.setBezeled_(False)
        entry.setBordered_(False)
        entry.setDrawsBackground_(False)
        entry.setFocusRingType_(1)  # NSFocusRingTypeNone
        entry.setFont_(font)
        entry.setTextColor_(st["fg"])
        entry.setPlaceholderAttributedString_(NSAttributedString.alloc().initWithString_attributes_(
            theme.placeholder, {NSFontAttributeName: font, NSForegroundColorAttributeName: st["fg"].colorWithAlphaComponent_(0.45)}))
        entry.cell().setUsesSingleLineMode_(True)
        entry.cell().setScrollable_(True)
        entry.setDelegate_(self.delegate)
        field_box.addSubview_(entry)
        hint = NSTextField.labelWithString_("Enter to ask · Esc to close · /new fresh session · /settings")
        hint.setFont_(hint_font)
        hint.setTextColor_(st["hint"])
        if st.get("hint_shadow"):  # white hint on light frost: a soft shadow keeps it readable
            shadow = AppKit.NSShadow.alloc().init()
            shadow.setShadowColor_(NSColor.colorWithWhite_alpha_(0, 0.6))
            shadow.setShadowBlurRadius_(3)
            shadow.setShadowOffset_((0, -1))
            hint.setShadow_(shadow)
        hint.setFrame_(NSMakeRect(self.PAD_X, self.PAD_Y - 2, self.WIDTH, hint_h))
        card.addSubview_(field_box)
        card.addSubview_(hint)
        panel.setContentView_(root)

        self.panel, self.entry = panel, entry
        panel.makeKeyAndOrderFront_(None)
        panel.makeFirstResponder_(entry)
        editor = entry.currentEditor()
        if editor is not None:
            editor.setInsertionPointColor_(st["fg"])

    def hide(self):
        if self.panel:
            panel, self.panel = self.panel, None
            panel.orderOut_(None)
            AppHelper.callAfter(panel.close)  # not from inside its own event handler

    # scripted demos
    def set_text(self, text):
        self.entry.setStringValue_(text)

    def activate(self):
        self.on_submit(str(self.entry.stringValue()).strip())


# --------------------------------------------------------------------------- screenshots

SCREEN_PERMISSION = ("Flippy needs Screen Recording permission. Turn it on in System Settings → Privacy & Security "
                     "→ Screen & System Audio Recording, then restart Flippy.")


class Screenshotter:
    def take(self, on_done, timeout_s=15):
        """Calls on_done(path, None) on success or on_done(None, error_str), on the main thread."""
        if not CGPreflightScreenCaptureAccess():
            CGRequestScreenCaptureAccess()  # shows the system prompt the first time
            loop.idle_add(on_done, None, SCREEN_PERMISSION)
            return
        fd, path = tempfile.mkstemp(prefix="flippy-", suffix=".png")
        os.close(fd)

        def run():
            try:
                r = subprocess.run(["/usr/sbin/screencapture", "-x", "-m", "-t", "png", path],
                                   capture_output=True, timeout=timeout_s)
                ok = r.returncode == 0 and os.path.getsize(path) > 0
                err = None if ok else (r.stderr.decode().strip() or f"screencapture exited {r.returncode}")
            except subprocess.TimeoutExpired:
                err = "screenshot timed out"
            if err:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            loop.idle_add(on_done, None if err else path, err)
        threading.Thread(target=run, daemon=True).start()


# --------------------------------------------------------------------------- menu bar

class MenuTarget(NSObject, protocols=[objc.protocolNamed("NSMenuDelegate")]):
    def act_(self, sender):
        cmd = str(sender.representedObject())
        p = self.platform
        if cmd == "setup":
            p.open_setup()
        elif cmd == "help-toggle":
            p.command(f"help-mode {'off' if settings.get('help', 'mode') != 'off' else 'quiet'}")
        elif cmd == "tips-toggle":
            p.command(f"help-mode {'quiet' if settings.get('help', 'mode') == 'tips' else 'tips'}")
        elif cmd == "goal-front":
            p.ask_goal()
        elif cmd == "watch-front":
            if p.menu_front:
                p.command(f"watch-app {p.menu_front[0]}")
        else:
            p.command(cmd)

    def menuWillOpen_(self, menu):
        self.platform.refresh_help_menu()


MENU = [("Ask about the screen", "ask", "ask"), ("Circle and ask", "draw", "draw"), None,
        ("Help when I'm stuck", "help-toggle", None), ("Tips while I work", "tips-toggle", None),
        ("Watch this app", "watch-front", None), ("Set a goal…", "goal-front", None), None,
        ("Preview the look", "preview", None), ("Settings…", "settings", None), ("New session", "reset", None),
        None, ("Check for updates…", "update", None), ("Setup…", "setup", None), ("Quit Flippy", "quit", None)]


# --------------------------------------------------------------------------- platform

class Platform:
    hide_settle_ms = HIDE_SETTLE_MS

    def __init__(self):
        self.overlay = Overlay()
        self.screenshotter = Screenshotter()
        self.settings_win = None
        self.setup_win = None
        self.nudge = Nudge()
        self.double_tap = hotkeys.DoubleTap()
        self.command = lambda cmd: "not ready"

    def input_box(self, on_submit, on_cancel):
        return InputBox(on_submit, on_cancel)

    def apply_theme(self, theme):
        pass  # the question box reads box_style() each time it opens

    def start(self, command):
        """Hotkeys and the menu bar icon, once the controller exists."""
        self.command = command
        self._bind_keys()
        settings.on_change(lambda section, key, value: section == "keys" and self._bind_keys())
        self._menu_bar()
        from .setup_window import needs_setup
        if needs_setup():
            loop.timeout_add(300, lambda: self.open_setup())

    def open_setup(self):
        from .setup_window import SetupWindow
        if self.setup_win is None:
            self.setup_win = SetupWindow(lambda: self.command("settings"), lambda: setattr(self, "setup_win", None))
        self.setup_win.present()

    def _bind_keys(self):
        for hid, name in ((1, "ask"), (2, "draw")):
            err = hotkeys.register(hid, settings.get("keys", name), lambda n=name: self.command(n))
            if err:
                print(f"flippy: hotkey for {name}: {err}", flush=True)
        pause = settings.get("keys", "pause")
        err = self.double_tap.set(None if pause == "off" else pause[len("double-"):],
                                  lambda: self.command("pause-toggle"))
        if err:
            print(f"flippy: pause shortcut: {err}", flush=True)
        if getattr(self, "menu_items", None):
            self._label_menu()

    def _menu_bar(self):
        self.status = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self._status_icon()
        settings.on_change(lambda section, key, value: section == "look" and key in ("pointer", "theme")
                           and self._status_icon())  # the icon is the equipped pointer
        self.target = MenuTarget.alloc().init()
        self.target.platform = self
        menu = NSMenu.alloc().init()
        self.menu_items = {}
        self.help_items = {}
        self.menu_front = None
        for entry in MENU:
            if entry is None:
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            title, cmd, key = entry
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, "act:", "")
            item.setTarget_(self.target)
            item.setRepresentedObject_(cmd)
            menu.addItem_(item)
            if key:
                self.menu_items[key] = (item, title)
            if cmd in ("help-toggle", "tips-toggle", "watch-front", "goal-front"):
                self.help_items[cmd] = item
        menu.setDelegate_(self.target)
        self.status.setMenu_(menu)
        self._label_menu()

    def refresh_help_menu(self):
        """The menu is opening: the app in front is the one they're working in (Flippy never activates)."""
        app, name, pid = sensors.frontmost()
        self.menu_front = (app, name) if app and pid != os.getpid() else None
        mode = settings.get("help", "mode")
        self.help_items["help-toggle"].setState_(1 if mode != "off" else 0)
        self.help_items["tips-toggle"].setState_(1 if mode == "tips" else 0)
        watch_item, goal_item = self.help_items["watch-front"], self.help_items["goal-front"]
        if self.menu_front:
            watched = self.menu_front[0] in settings.get_list("help", "apps")
            watch_item.setTitle_(f"Watch {self.menu_front[1]}")
            watch_item.setState_(1 if watched else 0)
            goal_item.setTitle_(f"Set a goal for {self.menu_front[1]}…")
        else:
            watch_item.setTitle_("Watch this app")
            watch_item.setState_(0)
            goal_item.setTitle_("Set a goal…")
        watch_item.setEnabled_(bool(self.menu_front))
        goal_item.setEnabled_(bool(self.menu_front))

    def ask_goal(self):
        """What do they want to do in this app? Steers its tips."""
        if not self.menu_front:
            return
        app, name = self.menu_front
        from .. import tips
        deck = tips.Deck.load(app)
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(f"What do you want to do in {name}?")
        alert.setInformativeText_("Flippy's tips for this app will be about it. For example: make a drum loop, "
                                  "write a CLI in Rust, mix vocals.")
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 24))
        field.setStringValue_(deck.goal if deck else "")
        alert.setAccessoryView_(field)
        alert.addButtonWithTitle_("Save")
        alert.addButtonWithTitle_("Cancel")
        NSApp.activateIgnoringOtherApps_(True)
        alert.window().setInitialFirstResponder_(field)
        if alert.runModal() == AppKit.NSAlertFirstButtonReturn:
            self.flippy.set_goal(app, str(field.stringValue()), name)
            if app not in settings.get_list("help", "apps"):
                self.command(f"watch-app {app}")
            if settings.get("help", "mode") != "tips":
                settings.set("help", "mode", "tips")  # a goal is for tips: turn them on

    # --- help mode (flippy/watch.py) ---
    def sample(self):
        return sensors.sample()

    def show_nudge(self, offer, on_help, on_later, on_mute):
        self.nudge.show(offer, on_help, on_later, on_mute)

    def show_tip(self, app_name, text, got_it, knew, show_me):
        self.nudge.card(f"Tip for {app_name}", text, [("Knew that", knew), ("Show me", show_me), ("Got it", got_it)],
                        on_timeout=got_it, timeout_s=25)

    def hide_nudge(self):
        self.nudge.hide()

    def nudge_visible(self):
        return self.nudge.visible

    def _status_icon(self):
        try:
            img = statusicon.image()
        except Exception as e:  # never lose the menu bar icon over a drawing problem
            print(f"flippy: menu bar icon: {e}", flush=True)
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_("cursorarrow.rays", "Flippy")
        img.setAccessibilityDescription_("Flippy")
        self.status.button().setImage_(img)

    def _label_menu(self):
        for key, (item, title) in self.menu_items.items():
            item.setTitle_(f"{title}    {hotkeys.pretty(settings.get('keys', key))}")

    def listen(self, path, handle):
        """Serve the flippy-ask socket: one command line in, handle(cmd) -> one reply line out."""
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        srv.listen(8)

        def on_main(line):
            done, out = threading.Event(), {}

            def run():
                try:
                    out["reply"] = handle(line)
                except Exception as e:  # keep serving
                    out["reply"] = f"error: {e}"
                done.set()
            AppHelper.callAfter(run)
            done.wait(10)
            return out.get("reply", "timeout")

        def serve():
            while True:
                conn, _ = srv.accept()
                with conn:
                    conn.settimeout(3)
                    data = b""
                    try:
                        while b"\n" not in data and len(data) < 65536:
                            chunk = conn.recv(4096)
                            if not chunk:
                                break
                            data += chunk
                        line = data.decode(errors="replace").strip() or "ask"
                        conn.sendall((on_main(line) + "\n").encode())
                    except OSError:
                        pass
        threading.Thread(target=serve, daemon=True).start()

    def open_settings(self, on_preview, on_reset):
        from .settings_window import SettingsWindow  # local: only built when asked for
        if self.settings_win is None:
            self.settings_win = SettingsWindow(on_preview, on_reset, lambda: setattr(self, "settings_win", None),
                                               command=self.command)
        self.settings_win.present()

    def demo_pointer(self, name, on_saved):
        """Scripted demo: draw a pointer in the editor and save it."""
        from . import pointer_editor
        from .. import pixelart, pointers
        ed = pointer_editor.PixelEditor(lambda n: None)
        ed.present()
        def set_tool(key):
            ed.tool = key
            ed.seg.setSelectedSegment_(ed.tools.index(key))

        def done():
            ed.name.setStringValue_(name)
            ed._save()
            on_saved(pointers.PREFIX + name)
        pixelart.demo_paint(ed.art, ed._redraw, set_tool, lambda col: setattr(ed, "color", col), done)

    # --- demo recording (scripts/demo_mac.py): run as Flippy's children, so they use its Screen Recording ---
    def screenshot_to(self, path):
        subprocess.run(["/usr/sbin/screencapture", "-x", "-m", "-t", "png", path], timeout=15)

    def start_recording(self, path):
        """ffmpeg screen capture to path; path + '.json' gets the clocks to line events up with frames."""
        self.stop_recording()
        log = open(path + ".log", "w")
        self.recorder = subprocess.Popen(
            ["ffmpeg", "-y", "-hide_banner", "-f", "avfoundation", "-capture_cursor", "1", "-framerate", "30",
             "-i", "Capture screen 0:none", "-c:v", "h264_videotoolbox", "-b:v", "24M", "-pix_fmt", "yuv420p", path],
            stdin=subprocess.PIPE, stdout=log, stderr=log)
        clocks = {"wall": time.time(), "mono": time.monotonic()}  # avfoundation stamps frames with the monotonic clock
        with open(path + ".json", "w") as f:
            json.dump(clocks, f)
        self.recording = path

    def stop_recording(self):
        rec = getattr(self, "recorder", None)
        if rec and rec.poll() is None:
            rec.stdin.write(b"q")  # ffmpeg's own clean stop: finishes the file
            rec.stdin.flush()
            try:
                rec.wait(20)
            except subprocess.TimeoutExpired:
                rec.kill()
        self.recorder = None

    def click(self, x, y, double=False):
        """Post a real left click at (x, y) on the main display (logical px, top-left origin)."""
        if not Quartz.CGPreflightPostEventAccess():
            Quartz.CGRequestPostEventAccess()  # the system prompt, the first time
            return ("Flippy needs the Accessibility permission to click: System Settings > Privacy & Security > "
                    "Accessibility, turn on Flippy, then restart it")
        pt = Quartz.CGPointMake(x, y)
        move = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, pt, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, move)
        time.sleep(0.05)
        for n in (1, 2) if double else (1,):
            for kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
                ev = Quartz.CGEventCreateMouseEvent(None, kind, pt, Quartz.kCGMouseButtonLeft)
                Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, n)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
                time.sleep(0.03)
        return "ok"

    def watch_clicks(self, fn):
        """fn(x, y) on every left click in other apps (logical px, top-left origin). No permission needed."""
        self.unwatch_clicks()

        def on_click(event):
            p, f = NSEvent.mouseLocation(), main_screen().frame()
            fn(p.x - f.origin.x, f.origin.y + f.size.height - p.y)
        self.click_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(AppKit.NSEventMaskLeftMouseDown,
                                                                                  on_click)

    def unwatch_clicks(self):
        if getattr(self, "click_monitor", None) is not None:
            NSEvent.removeMonitor_(self.click_monitor)
            self.click_monitor = None

    def press_nudge(self, title):
        return self.nudge.press(title)

    def restart(self, full_install=False):
        """Start a fresh Flippy and quit this one. full_install: rerun ./install.sh first (the app launcher changed)."""
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        app = os.environ.get("FLIPPY_APP")
        if full_install:
            cmd = f"sleep 1; '{root}/install.sh' >> ~/Library/Logs/flippy.log 2>&1"
        elif app:
            cmd = f"sleep 1; open '{app}'"
        else:
            cmd = f"sleep 1; '{root}/bin/flippy-ask' start"
        subprocess.Popen(["/bin/sh", "-c", cmd], start_new_session=True)
        self.quit()

    def show_update(self, rel, install, later):
        notes = next((ln.strip("-*# ").strip() for ln in rel["notes"].splitlines() if ln.strip("-*# ").strip()),
                     "A new version is ready.")
        self.nudge.card(f"Flippy {rel['version']} is out", notes,
                        [("What's new", lambda: subprocess.Popen(["open", rel["url"]])), ("Later", later),
                         ("Install", install)])

    def quit(self):
        self.stop_recording()
        AppHelper.callAfter(NSApp.terminate_, None)

    def screen_size(self):
        f = main_screen().frame()
        return f.size.width, f.size.height

    def scale(self):
        return main_screen().backingScaleFactor()


def _already_running(sock_path):
    """Opening Flippy.app again while it runs: show the settings there instead of starting twice."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(sock_path)
            s.sendall(b"settings\n")
            s.recv(64)
        return True
    except OSError:
        return False


def run(make_app):
    """Start Cocoa and call make_app(platform) once it's up."""
    from ..daemon import SOCK_PATH
    if _already_running(SOCK_PATH):
        print("flippy: already running; opened its settings", flush=True)
        return
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # no Dock icon
    global PLATFORM
    platform = PLATFORM = Platform()
    flippy = make_app(platform)
    platform.flippy = flippy
    platform.start(flippy.command)
    AppHelper.runEventLoop(installInterrupt=True)
