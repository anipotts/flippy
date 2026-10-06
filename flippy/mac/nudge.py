"""Help mode's cards on macOS: a small non-activating glass panel, top right under the menu bar.

"Need a hand?" (Help / Not now / Don't ask in <app>) and tips (Got it / Knew that /
Show me). It never takes focus from the app being learned, and goes away by
itself after a while.
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
        """help mode: "Need a hand?" with Help / Not now / Don't ask in <app>."""
        self.card(offer.headline(), offer.detail(), [("Not now", on_later), ("Help", on_help)],
                  (f"Don't ask in {offer.app_name}", on_mute), on_timeout=on_later)

    def card(self, head_text, detail_text, buttons, link=None, on_timeout=None, timeout_s=TIMEOUT_S):
        """head + detail, a right-aligned row of buttons [(title, fn)] (the last one is the default),
        and an optional small link (title, fn) underneath. Any choice closes it."""
        self.hide()
        self.keep = []

        def act(fn):
            def go():
                self.hide()
                fn()
            return go
        head = label(head_text, 13, bold=True, color=NSColor.whiteColor(), wrap_width=W - 2 * PAD)
        detail = label(detail_text, 12, color=NSColor.colorWithWhite_alpha_(1, 0.8), wrap_width=W - 2 * PAD)
        btns = [button(title, act(fn), self.keep, primary=(i == len(buttons) - 1)) for i, (title, fn) in enumerate(buttons)]
        small = None
        if link:
            small = button(link[0], act(link[1]), self.keep)
            small.setBordered_(False)
            small.setContentTintColor_(NSColor.colorWithWhite_alpha_(1, 0.6))
            small.setFont_(AppKit.NSFont.systemFontOfSize_(11))
            small.sizeToFit()

        y = PAD
        hh, dh = head.frame().size.height, detail.frame().size.height
        bh = max(b.frame().size.height for b in btns)
        h = PAD + hh + 4 + dh + 12 + bh + (6 + small.frame().size.height - 4 if small else 0) + PAD
        content = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, W, h))
        for v, x, yy in ((head, PAD, y), (detail, PAD, y + hh + 4)):
            v.setFrameOrigin_((x, yy))
            content.addSubview_(v)
        y += hh + 4 + dh + 12
        x = W - PAD
        for b in reversed(btns):
            x -= b.frame().size.width
            b.setFrameOrigin_((x, y))
            content.addSubview_(b)
            x -= 8
        if small:
            small.setFrameOrigin_((PAD - 4, y + bh + 4))
            content.addSubview_(small)

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
        if on_timeout:
            self.timer = loop.timeout_add(int(timeout_s * 1000), lambda: act(on_timeout)() and False)

    def hide(self):
        if self.timer:
            loop.source_remove(self.timer)
            self.timer = 0
        if self.panel:
            self.panel.orderOut_(None)
            self.panel = None
