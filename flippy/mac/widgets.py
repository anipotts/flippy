"""Small AppKit helpers for the settings window and pointer editors: callbacks, labels, a form layout."""
from AppKit import (NSButton, NSColor, NSFont, NSPopUpButton, NSSlider, NSTextField, NSView,
                    NSBezelStyleRounded, NSButtonTypeSwitch)
from Foundation import NSMakeRect, NSObject


class Target(NSObject):
    """target/action -> a Python callable. Keep a reference (Form.keep) or it's collected."""

    def fire_(self, sender):
        self.fn(sender)


def target(fn):
    t = Target.alloc().init()
    t.fn = fn
    return t


class FlippedView(NSView):
    def isFlipped(self):
        return True


def label(text, size=13, bold=False, color=None, wrap_width=None):
    lab = NSTextField.wrappingLabelWithString_(text) if wrap_width else NSTextField.labelWithString_(text)
    lab.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    if color:
        lab.setTextColor_(color)
    if wrap_width:
        lab.setPreferredMaxLayoutWidth_(wrap_width)
    lab.sizeToFit()
    if wrap_width:
        lab.setFrameSize_((wrap_width, lab.fittingSize().height))
    return lab


def button(title, fn, keep, primary=False):
    b = NSButton.buttonWithTitle_target_action_(title, None, None)
    t = target(lambda s: fn())
    keep.append(t)
    b.setTarget_(t)
    b.setAction_("fire:")
    b.setBezelStyle_(NSBezelStyleRounded)
    if primary:
        b.setKeyEquivalent_("\r")
    b.sizeToFit()
    return b


def checkbox(title, on, fn, keep):
    b = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
    b.setButtonType_(NSButtonTypeSwitch)
    b.setTitle_(title)
    b.setState_(1 if on else 0)
    t = target(lambda s: fn(bool(s.state())))
    keep.append(t)
    b.setTarget_(t)
    b.setAction_("fire:")
    b.sizeToFit()
    return b


def popup(options, current, fn, keep, width=220):
    """options: [(value, label)]; fn(value) on change."""
    p = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(0, 0, width, 26), False)
    t = target(lambda s: fn(t.values[s.indexOfSelectedItem()]))
    keep.append(t)
    p.setTarget_(t)
    p.setAction_("fire:")
    set_popup(p, options, current)
    return p


def set_popup(p, options, current):
    """Replace a popup()'s options (the values live on its Target)."""
    p.removeAllItems()
    p.addItemsWithTitles_([lab for _, lab in options])
    values = [v for v, _ in options]
    p.target().values = values
    p.selectItemAtIndex_(values.index(current) if current in values else 0)


def slider(lo, hi, step, value, fn, keep, digits=0, width=170):
    """A slider with its value shown next to it. fn(value) while dragging."""
    box = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width + 52, 24))
    s = NSSlider.sliderWithValue_minValue_maxValue_target_action_(value, lo, hi, None, None)
    s.setFrame_(NSMakeRect(0, 0, width, 24))
    s.setContinuous_(True)
    val = NSTextField.labelWithString_("")
    val.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(12, 0))
    val.setFrame_(NSMakeRect(width + 8, 3, 44, 18))

    def fmt(v):
        return f"{v:.{digits}f}" if digits else str(int(v))
    val.setStringValue_(fmt(value))

    def changed(sender):
        v = round(round(sender.doubleValue() / step) * step, 4)
        v = int(v) if not digits else round(v, digits)
        val.setStringValue_(fmt(v))
        fn(v)
    t = target(changed)
    keep.append(t)
    s.setTarget_(t)
    s.setAction_("fire:")
    box.addSubview_(s)
    box.addSubview_(val)
    return box


class Form:
    """Top-down layout of grouped rows (title + subtitle on the left, control on the right)."""

    def __init__(self, width):
        self.width = width
        self.view = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, width, 10))
        self.y = 20
        self.keep = []
        self.pad = 24

    def group(self, title, description=None):
        if self.y > 20:
            self.y += 14
        lab = label(title, 13, bold=True)
        self._place(lab, self.pad, self.y)
        self.y += lab.frame().size.height + 2
        if description:
            d = label(description, 11, color=NSColor.secondaryLabelColor(), wrap_width=self.width - 2 * self.pad)
            self._place(d, self.pad, self.y)
            self.y += d.frame().size.height + 2
        self.y += 6

    def row(self, title, subtitle=None, control=None):
        left_w = self.width - 2 * self.pad - (control.frame().size.width + 12 if control else 0)
        t = label(title, 13)
        h = t.frame().size.height
        s = None
        if subtitle:
            s = label(subtitle, 11, color=NSColor.secondaryLabelColor(), wrap_width=max(left_w, 120))
            h += s.frame().size.height + 1
        row_h = max(h, control.frame().size.height if control else 0) + 12
        top = self.y + (row_h - h) / 2
        self._place(t, self.pad, top)
        if s:
            self._place(s, self.pad, top + t.frame().size.height + 1)
        if control:
            cw, ch = control.frame().size.width, control.frame().size.height
            self._place(control, self.width - self.pad - cw, self.y + (row_h - ch) / 2)
        self.y += row_h
        return control

    def add(self, view, x=None, height=None):
        self._place(view, self.pad if x is None else x, self.y)
        self.y += (height or view.frame().size.height) + 8
        return view

    def buttons(self, *btns):
        """A right-aligned row of controls."""
        x = self.width - self.pad
        h = max(b.frame().size.height for b in btns)
        for b in reversed(btns):
            x -= b.frame().size.width
            self._place(b, x, self.y + (h - b.frame().size.height) / 2)
            x -= 8
        self.y += h + 8

    def _place(self, v, x, y):
        f = v.frame()
        v.setFrame_(NSMakeRect(x, y, f.size.width, f.size.height))
        self.view.addSubview_(v)

    def finish(self):
        self.view.setFrameSize_((self.width, self.y + 20))
        return self.view

