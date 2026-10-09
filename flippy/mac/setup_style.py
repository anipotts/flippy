"""Small, setup-only AppKit pieces. Native controls keep their normal behavior."""
from AppKit import (NSButton, NSColor, NSFont, NSFontAttributeName, NSForegroundColorAttributeName, NSImage,
                    NSImageView, NSView, NSFontWeightMedium, NSFontWeightSemibold)
from Foundation import NSAttributedString, NSMakeRect
from .widgets import label, target

# Black, with white-ish gray outlines; buttons and cards have sharp corners.
BACKGROUND = (0, 0, 0)
SURFACE = (0, 0, 0)
OUTLINE = (0.80, 0.80, 0.82)   # buttons, cards, keycaps
BORDER = (0.22, 0.22, 0.23)    # dividers
PRESSED = (0.16, 0.16, 0.17)
TEXT = (0.94, 0.945, 0.95)
MUTED = (0.62, 0.64, 0.68)


def color(rgb):
    return NSColor.colorWithSRGBRed_green_blue_alpha_(*rgb, 1)


class Canvas(NSView):
    def isFlipped(self):
        return True


def panel(width, height, surface=BACKGROUND, radius=0, outline=None):
    view = Canvas.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    view.setWantsLayer_(True)
    view.layer().setBackgroundColor_(color(surface).CGColor())
    view.layer().setCornerRadius_(radius)
    if outline:
        view.layer().setBorderWidth_(1)
        view.layer().setBorderColor_(color(outline).CGColor())
    return view


def card(width, height):
    return panel(width, height, SURFACE, outline=OUTLINE)


def _outline(control, title=None):
    control.setBordered_(False)
    control.setWantsLayer_(True)
    layer = control.layer()
    layer.setCornerRadius_(0)
    layer.setBorderWidth_(1)
    layer.setBorderColor_(color(OUTLINE).CGColor())
    layer.setBackgroundColor_(color(SURFACE).CGColor())
    if title is not None:
        control.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(title, {
            NSForegroundColorAttributeName: color(TEXT),
            NSFontAttributeName: NSFont.systemFontOfSize_weight_(12, NSFontWeightMedium)}))


class OutlineButton(NSButton):
    """A black, sharp-cornered button with a light outline; darkens while pressed."""
    def highlight_(self, on):
        self.layer().setBackgroundColor_(color(PRESSED if on else SURFACE).CGColor())

    def setTitle_(self, title):
        _outline(self, title)


def button(title, fn, keep, primary=False):
    b = OutlineButton.buttonWithTitle_target_action_(title, None, None)
    t = target(lambda s: fn())
    keep.append(t)
    b.setTarget_(t)
    b.setAction_("fire:")
    if primary:
        b.setKeyEquivalent_("\r")
    _outline(b, title)
    b.sizeToFit()
    return b


def outline_popup(popup):
    _outline(popup)
    return popup


def place(parent, view, x, y, width=None, height=None):
    frame = view.frame()
    view.setFrame_(NSMakeRect(x, y, width or frame.size.width, height or frame.size.height))
    parent.addSubview_(view)
    return view


def text(parent, value, x, y, width, size=12, bold=False, muted=False):
    view = label(value, size, color=color(MUTED if muted else TEXT), wrap_width=width)
    if bold:
        view.setFont_(NSFont.systemFontOfSize_weight_(size, NSFontWeightSemibold))
    place(parent, view, x, y)
    return view


def rule(parent, y, width, x=24):
    place(parent, panel(width, 1, BORDER), x, y)


def symbol(name, description, size=22):
    view = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, size, size))
    image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, description)
    view.setImage_(image)
    view.setContentTintColor_(color(MUTED))
    view.setAccessibilityLabel_(description)
    return view


def section(parent, number, title, subtitle, y, width):
    circle = panel(26, 26, SURFACE, 13, outline=OUTLINE)
    text(circle, str(number), 9, 4, 14, 13, bold=True)
    place(parent, circle, 24, y)
    text(parent, title, 62, y - 1, width - 86, 16, bold=True)
    text(parent, subtitle, 62, y + 20, width - 86, 11, muted=True)


def shortcut_tokens(combo):
    """Display keycaps in macOS modifier order, including double-tap shortcuts."""
    names = {'cmd': '⌘', 'shift': '⇧', 'option': '⌥', 'opt': '⌥', 'alt': '⌥',
             'ctrl': '⌃', 'control': '⌃'}
    if combo == 'off':
        return ['Off']
    if combo.startswith('double-'):
        key = names.get(combo[7:], combo[7:].capitalize())
        return [key, key]
    parts = [part.strip().lower() for part in combo.split('+') if part.strip()]
    if not parts:
        return []
    modifiers = {names.get(part, part) for part in parts[:-1]}
    ordered = [key for key in ('⌃', '⌥', '⇧', '⌘') if key in modifiers]
    return ordered + [parts[-1].capitalize() if len(parts[-1]) > 1 else parts[-1].upper()]


def keycaps(parent, combo, x, y):
    for key in shortcut_tokens(combo):
        width = 60 if len(key) > 1 else 30
        cap = panel(width, 28, SURFACE, outline=OUTLINE)
        lab = text(cap, key, 0, 6, width, 12, bold=True)
        lab.setAlignment_(1)
        place(parent, cap, x, y)
        x += width + 6
    return x
