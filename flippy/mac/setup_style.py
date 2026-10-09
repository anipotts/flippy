"""The setup and settings windows' look: black, gray outlines, sharp corners. Controls keep their normal behavior."""
from AppKit import (NSButton, NSColor, NSFont, NSFontAttributeName, NSForegroundColorAttributeName, NSImage,
                    NSImageView, NSView, NSFontWeightMedium, NSFontWeightSemibold)
import objc
from Foundation import NSAttributedString, NSMakeRect
from .widgets import label, target

# Black, with white-ish gray outlines; buttons and cards have sharp corners.
BACKGROUND = (0, 0, 0)
SURFACE = (0, 0, 0)
OUTLINE = (0.50, 0.50, 0.52)   # buttons, cards, keycaps
BORDER = (0.22, 0.22, 0.23)    # dividers
PRESSED = (0.16, 0.16, 0.17)
TEXT = (0.94, 0.945, 0.95)
MUTED = (0.62, 0.64, 0.68)


def color(rgb):
    return NSColor.colorWithSRGBRed_green_blue_alpha_(*rgb, 1)


class Canvas(NSView):
    def isFlipped(self):
        return True


class Diamond(Canvas):
    """A rhombus outline (the section numbers sit inside one)."""
    def drawRect_(self, rect):
        from AppKit import NSBezierPath
        w, h = self.bounds().size.width, self.bounds().size.height
        path = NSBezierPath.bezierPath()
        path.moveToPoint_((w / 2, 0.5))
        path.lineToPoint_((w - 0.5, h / 2))
        path.lineToPoint_((w / 2, h - 0.5))
        path.lineToPoint_((0.5, h / 2))
        path.closePath()
        path.setLineWidth_(1)
        color(OUTLINE).setStroke()
        path.stroke()


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


def _outline(control, title=None, bright=True, edge=OUTLINE):
    control.setBordered_(False)
    control.setWantsLayer_(True)
    layer = control.layer()
    layer.setCornerRadius_(0)
    layer.setBorderWidth_(1)
    layer.setBorderColor_(color(edge).CGColor())
    layer.setBackgroundColor_(color(SURFACE).CGColor())
    if title is not None:
        control.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(title, {
            NSForegroundColorAttributeName: color(TEXT if bright else MUTED).colorWithAlphaComponent_(
                1 if control.isEnabled() else 0.4),
            NSFontAttributeName: NSFont.systemFontOfSize_weight_(12, NSFontWeightMedium)}))


class OutlineButton(NSButton):
    """A black, sharp-cornered button with a light outline; darkens while pressed."""
    selected = None  # a tab: True = the page shown

    def highlight_(self, on):
        self.layer().setBackgroundColor_(color(PRESSED if on else SURFACE).CGColor())

    def setTitle_(self, title):
        self._title = title
        _outline(self, title, bright=self.selected is not False, edge=TEXT if self.selected else OUTLINE)

    def setEnabled_(self, on):
        objc.super(OutlineButton, self).setEnabled_(on)
        self.setTitle_(getattr(self, "_title", None) or self.title())

    def set_selected(self, on):
        self.selected = bool(on)
        self.setTitle_(self._title)


def button(title, fn, keep, primary=False):
    b = OutlineButton.buttonWithTitle_target_action_(title, None, None)
    t = target(lambda s: fn())
    keep.append(t)
    b.setTarget_(t)
    b.setAction_("fire:")
    if primary:
        b.setKeyEquivalent_("\r")
    b.setTitle_(title)
    b.sizeToFit()
    w, h = b.frame().size
    b.setFrameSize_((w + 16, max(h, 26)))
    return b


def outline_popup(popup):
    _outline(popup)
    return popup


def check(on, fn, keep):
    """A square outlined checkbox: ✓ when on. fn(bool) on change."""
    b = OutlineButton.buttonWithTitle_target_action_("", None, None)
    b.setFrameSize_((22, 22))

    def show():
        b.setTitle_("✓" if b.on else "")

    def flip(sender):
        b.on = not b.on
        show()
        fn(b.on)
    t = target(flip)
    keep.append(t)
    b.setTarget_(t)
    b.setAction_("fire:")
    b.on = bool(on)
    show()
    b.setAccessibilityRole_("AXCheckBox")
    return b


def outline_field(field, width=220, height=26):
    """A text field drawn black inside the outline, sharp corners: returns the outlined box holding it."""
    box = panel(width, height, SURFACE, outline=OUTLINE)
    field.setBezeled_(False)
    field.setBordered_(False)
    field.setDrawsBackground_(False)
    field.setTextColor_(color(TEXT))
    field.setFont_(NSFont.systemFontOfSize_(13))
    field.setFrame_(NSMakeRect(8, (height - 18) / 2, width - 16, 18))
    box.addSubview_(field)
    return box


def outline_slider(box):
    """widgets.slider()'s box: the track filled in gray instead of the system accent."""
    from AppKit import NSSlider
    for view in box.subviews():
        if isinstance(view, NSSlider):
            view.setTrackFillColor_(color(TEXT))
    return box


def flippy_mark(size):
    """The pointing hand with its click lines in the setup's grays, no tile behind it (an NSImageView)."""
    import math
    import cairo
    from AppKit import NSImageScaleProportionallyUpOrDown
    from Foundation import NSData
    from .. import themes
    scale = 2  # Retina
    rows = themes.HAND
    px = int(size * scale / 1.5 / len(rows))  # the hand plus its click lines (a third of its height) fit
    w, h = len(rows[0]) * px, len(rows) * px
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(size * scale), int(size * scale))
    cr = cairo.Context(surface)
    ox, oy = round((size * scale - w) / 2), round(size * scale - h - (size * scale - 1.38 * h) / 2)
    cr.set_antialias(cairo.ANTIALIAS_NONE)
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch != " ":
                cr.set_source_rgb(*(OUTLINE if ch == "#" else TEXT))
                cr.rectangle(ox + c * px, oy + r * px, px, px)
                cr.fill()
    cr.set_antialias(cairo.ANTIALIAS_DEFAULT)
    tip_x, tip_y = ox + (themes.HAND_TIP_COL + 0.5) * px, oy
    start, length = 0.15 * h, 0.19 * h
    cr.set_source_rgb(*MUTED)
    cr.set_line_width(0.075 * h)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for a in (-90, -130, -50, -165, -15):
        r = math.radians(a)
        cr.move_to(tip_x + start * math.cos(r), tip_y + start * math.sin(r))
        cr.line_to(tip_x + (start + length) * math.cos(r), tip_y + (start + length) * math.sin(r))
    cr.stroke()
    chunks = []
    surface.write_to_png(type("Sink", (), {"write": lambda self, b: chunks.append(b) or len(b)})())
    data = b"".join(chunks)
    image = NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(data, len(data)))
    image.setSize_((size, size))
    view = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, size, size))
    view.setImage_(image)
    view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
    view.setAccessibilityLabel_("Flippy")
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
    diamond = Diamond.alloc().initWithFrame_(NSMakeRect(0, 0, 30, 30))
    digit = text(diamond, str(number), 0, 6, 30, 13, bold=True)
    digit.setAlignment_(1)
    place(parent, diamond, 22, y - 2)
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
