"""Small, setup-only AppKit pieces. Native controls keep their normal behavior."""
from AppKit import (NSColor, NSFont, NSImage, NSImageView, NSView,
                    NSFontWeightSemibold)
from Foundation import NSMakeRect
from .widgets import label

BACKGROUND = (0.105, 0.11, 0.12)
SURFACE = (0.145, 0.15, 0.16)
BORDER = (0.245, 0.25, 0.265)
TEXT = (0.94, 0.945, 0.95)
MUTED = (0.62, 0.64, 0.68)


def color(rgb):
    return NSColor.colorWithSRGBRed_green_blue_alpha_(*rgb, 1)


class Canvas(NSView):
    def isFlipped(self):
        return True


def panel(width, height, surface=BACKGROUND, radius=0):
    view = Canvas.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    view.setWantsLayer_(True)
    view.layer().setBackgroundColor_(color(surface).CGColor())
    if radius:
        view.layer().setCornerRadius_(radius)
        view.layer().setBorderWidth_(1)
        view.layer().setBorderColor_(color(BORDER).CGColor())
    return view


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
    circle = panel(26, 26, (0.19, 0.20, 0.215), 13)
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
        cap = panel(width, 28, (0.19, 0.20, 0.215), 6)
        lab = text(cap, key, 0, 6, width, 12, bold=True)
        lab.setAlignment_(1)
        place(parent, cap, x, y)
        x += width + 6
    return x
