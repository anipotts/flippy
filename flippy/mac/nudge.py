"""The "Need a hand?" card on macOS: a small non-activating glass panel, top right under the menu bar.

Buttons: Help, Not now, and "Don't ask in <app>". It never takes focus from the
app being learned, and goes away by itself after TIMEOUT_S (counted as "Not now").
"""
import AppKit
from AppKit import (NSBackingStoreBuffered, NSColor, NSFloatingWindowLevel, NSPanel, NSScreen,
                    NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorFullScreenAuxiliary,
                    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel)
from Foundation import NSMakeRect

from .. import loop
from .widgets import FlippedView, button, label

TIMEOUT_S = 15
W, PAD = 300, 14


class Nudge:
    def __init__(self):
        self.panel = None
        self.timer = 0
        self.keep = []

    @property
    def visible(self):
        return self.panel is not None

    def show(self, offer, on_help, on_later, on_mute):
        self.hide()
        self.keep = []

        def act(fn):
            def go():
                self.hide()
                fn()
            return go
        head = label(offer.headline(), 13, bold=True, color=NSColor.whiteColor(), wrap_width=W - 2 * PAD)
        detail = label(offer.detail(), 11, color=NSColor.colorWithWhite_alpha_(1, 0.75), wrap_width=W - 2 * PAD)
        help_btn = button("Help", act(on_help), self.keep, primary=True)
        later = button("Not now", act(on_later), self.keep)
        mute = button(f"Don't ask in {offer.app_name}", act(on_mute), self.keep)
        mute.setBordered_(False)
        mute.setContentTintColor_(NSColor.colorWithWhite_alpha_(1, 0.6))
        mute.setFont_(AppKit.NSFont.systemFontOfSize_(11))
        mute.sizeToFit()

        y = PAD
        hh, dh = head.frame().size.height, detail.frame().size.height
        bh = help_btn.frame().size.height
        h = PAD + hh + 2 + dh + 12 + bh + 6 + mute.frame().size.height + PAD - 4
        content = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, W, h))
        for v, x, yy in ((head, PAD, y), (detail, PAD, y + hh + 2)):
            v.setFrameOrigin_((x, yy))
            content.addSubview_(v)
        y += hh + 2 + dh + 12
        help_btn.setFrameOrigin_((W - PAD - help_btn.frame().size.width, y))
        later.setFrameOrigin_((help_btn.frame().origin.x - 8 - later.frame().size.width, y))
        mute.setFrameOrigin_((PAD - 4, y + bh + 4))
        for v in (help_btn, later, mute):
            content.addSubview_(v)

        if hasattr(AppKit, "NSGlassEffectView"):  # Liquid Glass, smoky so white text reads anywhere
            root = AppKit.NSGlassEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, W, h))
            root.setCornerRadius_(18)
            root.setTintColor_(NSColor.colorWithWhite_alpha_(0.08, 0.55))
            root.setContentView_(content)
        else:
            root = content
            content.setWantsLayer_(True)
            content.layer().setBackgroundColor_(NSColor.colorWithWhite_alpha_(0.1, 0.92).CGColor())
            content.layer().setCornerRadius_(14)

        vis = NSScreen.screens()[0].visibleFrame()
        x = vis.origin.x + vis.size.width - W - 12
        top = vis.origin.y + vis.size.height - 12
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, top - h, W, h), NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, False)
        panel.setLevel_(NSFloatingWindowLevel)
        panel.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setReleasedWhenClosed_(False)
        panel.setHidesOnDeactivate_(False)
        panel.setAppearance_(AppKit.NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
        panel.setContentView_(root)
        panel.orderFrontRegardless()
        self.panel = panel
        self.timer = loop.timeout_add(TIMEOUT_S * 1000, lambda: act(on_later)() and False)

    def hide(self):
        if self.timer:
            loop.source_remove(self.timer)
            self.timer = 0
        if self.panel:
            self.panel.orderOut_(None)
            self.panel = None
