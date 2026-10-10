"""The setup, settings and Draw editor windows' look on GTK: black, gray outlines, sharp corners.

The GTK side of flippy/mac/setup_style.py, with the same colors. It's CSS on Flippy's own windows only (the
`flippy-ui` class), so the user's GTK theme and Flippy's overlay and question box are left alone. The font is set
here too: COSMIC passes the desktop's font through, and a serif one made the setup read like a letter.
"""
import math

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk, Pango, PangoCairo  # noqa: E402

from .. import themes  # noqa: E402

# the same values as flippy/mac/setup_style.py
BACKGROUND = (0, 0, 0)
OUTLINE = (0.50, 0.50, 0.52)   # buttons, cards, keycaps
BORDER = (0.22, 0.22, 0.23)    # dividers
PRESSED = (0.16, 0.16, 0.17)
TEXT = (0.94, 0.945, 0.95)
MUTED = (0.62, 0.64, 0.68)
FONT = '"Fira Sans", "Inter", "Noto Sans", sans-serif'


def css(rgb, alpha=1.0):
    r, g, b = (round(c * 255) for c in rgb)
    return f"rgba({r},{g},{b},{alpha})" if alpha < 1 else f"rgb({r},{g},{b})"


T, M, O, B, P = css(TEXT), css(MUTED), css(OUTLINE), css(BORDER), css(PRESSED)
CSS = f"""
window.flippy-ui, window.flippy-ui.csd, window.flippy-ui > .background {{
  background: #000; color: {T}; border-radius: 0; font-family: {FONT}; font-size: 13px; }}
window.flippy-ui.csd {{ box-shadow: 0 0 0 1px {B}, 0 8px 28px rgba(0,0,0,0.55); }}
window.flippy-ui headerbar {{ background: #000; color: {T}; box-shadow: none; border-bottom: 1px solid {B};
  border-radius: 0; min-height: 38px; }}
window.flippy-ui headerbar .title {{ font-weight: 600; font-size: 13px; }}
window.flippy-ui headerbar windowcontrols button {{ border: none; background: none; min-height: 22px; min-width: 22px;
  padding: 0; color: {M}; }}
window.flippy-ui headerbar windowcontrols button:hover {{ color: {T}; background: {P}; }}
window.flippy-ui scrolledwindow, window.flippy-ui viewport, window.flippy-ui stack {{ background: transparent; }}
window.flippy-ui undershoot, window.flippy-ui overshoot {{ background: none; box-shadow: none; }}

/* text */
window.flippy-ui label {{ color: {T}; }}
window.flippy-ui .muted, window.flippy-ui label.dim-label, window.flippy-ui row .subtitle {{ color: {M}; opacity: 1; }}
window.flippy-ui .title-1 {{ font-size: 25px; font-weight: 700; }}
window.flippy-ui .heading {{ font-size: 13px; font-weight: 600; }}
window.flippy-ui .section-title {{ font-size: 16px; font-weight: 600; }}
window.flippy-ui .small {{ font-size: 11px; }}
window.flippy-ui .tiny {{ font-size: 10px; }}
window.flippy-ui .bright {{ color: {T}; }}

/* outlined, sharp controls */
window.flippy-ui button, window.flippy-ui dropdown > button, window.flippy-ui menubutton > button {{
  background: #000; color: {T}; border: 1px solid {O}; border-radius: 0; box-shadow: none; outline: none;
  padding: 3px 12px; min-height: 24px; font-weight: 500; text-shadow: none; -gtk-icon-shadow: none; }}
window.flippy-ui button:hover {{ background: rgb(20,20,21); }}
window.flippy-ui button:active, window.flippy-ui button:checked {{ background: {P}; }}
window.flippy-ui button:disabled, window.flippy-ui button:disabled label {{ color: {css(TEXT, 0.4)};
  border-color: {css(OUTLINE, 0.5)}; }}
window.flippy-ui button:focus-visible {{ outline: 1px solid {T}; outline-offset: 1px; }}
window.flippy-ui button.tab, window.flippy-ui button.tool {{ color: {M}; margin-right: -1px; }}
window.flippy-ui button.tool {{ padding: 3px 9px; }}
window.flippy-ui button.selected, window.flippy-ui button.tab:checked {{
  box-shadow: inset 0 0 0 1px {T}; border-color: {T}; color: #fff; background: #000; }}
window.flippy-ui button.selected label, window.flippy-ui button.tab:checked label {{ color: #fff; }}
window.flippy-ui button.tab label, window.flippy-ui button.tool label {{ color: {M}; }}
window.flippy-ui button.swatch {{ padding: 0; min-height: 0; min-width: 0; border: none; background: none; }}
window.flippy-ui button.flat, window.flippy-ui button.thumb {{ border: none; background: none; padding: 0; }}
window.flippy-ui button.thumb:checked {{ background: none; }}
window.flippy-ui dropdown.attention > button {{ border: 2px solid {T}; padding: 2px 11px; }}
window.flippy-ui dropdown > button > box > stack > row {{ background: none; padding: 0; }}

window.flippy-ui popover > contents {{ background: #000; color: {T}; border: 1px solid {O}; border-radius: 0;
  box-shadow: none; padding: 2px; }}
window.flippy-ui popover > arrow {{ background: #000; border: 1px solid {O}; }}
window.flippy-ui popover listview > row, window.flippy-ui popover modelbutton {{ border-radius: 0; padding: 5px 8px; }}
window.flippy-ui popover listview > row:hover, window.flippy-ui popover listview > row:selected,
window.flippy-ui popover modelbutton:hover {{ background: {P}; }}

window.flippy-ui entry, window.flippy-ui spinbutton {{ background: #000; color: {T}; border: 1px solid {O};
  border-radius: 0; box-shadow: none; outline: none; min-height: 26px; caret-color: {T}; }}
window.flippy-ui entry:focus-within {{ border-color: {T}; outline: none; box-shadow: none; }}
window.flippy-ui entry > text > selection {{ background: {css(TEXT, 0.25)}; }}

window.flippy-ui checkbutton {{ padding: 0; }}
window.flippy-ui check {{ background: #000; border: 1px solid {O}; border-radius: 0; box-shadow: none;
  min-width: 18px; min-height: 18px; -gtk-icon-source: none; color: {T}; outline: none; }}
window.flippy-ui check:checked {{ -gtk-icon-source: -gtk-icontheme("object-select-symbolic"); background: #000;
  border-color: {T}; color: {T}; }}
window.flippy-ui check:hover {{ background: rgb(20,20,21); }}

window.flippy-ui switch {{ background: #000; border: 1px solid {O}; border-radius: 0; box-shadow: none;
  outline: none; min-width: 40px; }}
window.flippy-ui switch > slider {{ background: {M}; border-radius: 0; box-shadow: none; border: none;
  margin: 3px; min-width: 16px; min-height: 16px; }}
window.flippy-ui switch:checked {{ background: {P}; border-color: {T}; }}
window.flippy-ui switch:checked > slider {{ background: {T}; }}
window.flippy-ui switch:disabled {{ opacity: 0.4; }}

window.flippy-ui scale {{ padding: 8px 0; }}
window.flippy-ui scale > trough {{ background: {B}; border: none; border-radius: 0; min-height: 4px; outline: none; }}
window.flippy-ui scale > trough > highlight {{ background: {T}; border-radius: 0; }}
window.flippy-ui scale > trough > slider {{ background: {T}; border: 1px solid #000; border-radius: 0;
  box-shadow: none; min-width: 8px; min-height: 18px; margin: -8px -4px; }}
window.flippy-ui scale > value {{ color: {M}; font-feature-settings: "tnum"; min-width: 40px; }}

/* cards, keycaps, dividers */
window.flippy-ui .card {{ background: #000; border: 1px solid {O}; border-radius: 0; box-shadow: none; }}
window.flippy-ui .keycap {{ border: 1px solid {O}; min-height: 26px; min-width: 28px; font-weight: 600;
  font-size: 12px; padding: 0 8px; }}
window.flippy-ui .rule {{ background: {B}; min-height: 1px; min-width: 1px; }}

/* libadwaita's preference rows: plain rows on black, a divider above each group (like the macOS form) */
window.flippy-ui .page preferencesgroup {{ border-top: 1px solid {B}; padding-top: 14px; margin-top: 16px; }}
window.flippy-ui .page preferencesgroup:first-child {{ border-top: none; margin-top: 0; padding-top: 0; }}
window.flippy-ui preferencesgroup > box {{ border-spacing: 6px; }}
window.flippy-ui preferencesgroup > box > box.header {{ margin: 0; padding: 0; min-height: 0; }}
window.flippy-ui preferencesgroup > box > box.header label:not(.heading) {{ color: {M}; font-size: 11px;
  opacity: 1; }}
window.flippy-ui list.boxed-list {{ background: transparent; border: none; box-shadow: none; border-radius: 0; }}
window.flippy-ui list.boxed-list > row {{ background: transparent; border: none; border-radius: 0; min-height: 40px;
  padding: 0; }}
window.flippy-ui list.boxed-list > row:hover, window.flippy-ui list.boxed-list > row:active,
window.flippy-ui list.boxed-list > row:focus {{ background: none; }}
window.flippy-ui list.boxed-list > row > box.header {{ padding: 4px 0; margin: 0; min-height: 0; }}
window.flippy-ui row .title {{ font-size: 13px; }}
window.flippy-ui row .subtitle {{ font-size: 11px; }}
"""

_installed = False


def apply(win):
    """Give a window Flippy's look (installs the stylesheet once, scoped by the class)."""
    global _installed
    if not _installed:
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS, -1)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)
        _installed = True
    win.add_css_class("flippy-ui")
    return win


# ---- pieces
def label(text, *classes, wrap=False, xalign=0.0, width=None):
    lab = Gtk.Label(label=text, xalign=xalign, wrap=wrap, css_classes=list(classes))
    if wrap:
        lab.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        if width:
            lab.set_size_request(width, -1)
            lab.set_max_width_chars(1)  # wrap at the given width, not the label's natural one
    return lab


def button(text, fn, *classes):
    b = Gtk.Button(label=text, css_classes=list(classes))
    b.connect("clicked", lambda *_: fn())
    return b


def set_selected(btn, on):
    """A tab or tool: the one in use gets the bright outline and white text."""
    (btn.add_css_class if on else btn.remove_css_class)("selected")


def rule(vertical=False):
    return Gtk.Box(css_classes=["rule"], hexpand=not vertical, vexpand=vertical)


def card(orientation=Gtk.Orientation.HORIZONTAL, spacing=0):
    return Gtk.Box(orientation=orientation, spacing=spacing, css_classes=["card"])


def keycaps(tokens):
    box = Gtk.Box(spacing=6)
    for key in tokens:
        cap = Gtk.Label(label=key, css_classes=["card", "keycap"], xalign=0.5)
        cap.set_size_request(60 if len(key) > 1 else 30, 28)
        box.append(cap)
    return box


def diamond(number):
    """A section number inside an outlined rhombus."""
    area = Gtk.DrawingArea(content_width=30, content_height=30, valign=Gtk.Align.START)

    def draw(_a, cr, w, h):
        cr.move_to(w / 2, 0.5)
        cr.line_to(w - 0.5, h / 2)
        cr.line_to(w / 2, h - 0.5)
        cr.line_to(0.5, h / 2)
        cr.close_path()
        cr.set_source_rgb(*OUTLINE)
        cr.set_line_width(1)
        cr.stroke()
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(Pango.FontDescription.from_string("Fira Sans, Noto Sans, sans-serif Bold 10"))
        lay.set_text(str(number), -1)
        tw, th = lay.get_pixel_size()
        cr.move_to((w - tw) / 2, (h - th) / 2)
        cr.set_source_rgb(*TEXT)
        PangoCairo.show_layout(cr, lay)
    area.set_draw_func(draw)
    return area


def section(number, title, subtitle):
    """The diamond, then the section's title with a muted line under it."""
    row = Gtk.Box(spacing=14)
    row.append(diamond(number))
    words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
    words.append(label(title, "section-title"))
    words.append(label(subtitle, "muted", "small"))
    row.append(words)
    return row


def draw_mark(cr, size):
    """The pointing hand with its click lines in the setup's grays, no tile (setup_style.flippy_mark's drawing)."""
    rows = themes.HAND
    px = max(1, int(size / 1.5 / len(rows)))  # whole pixels, so it stays crisp; the hand and its click lines fit
    w, h = len(rows[0]) * px, len(rows) * px
    ox, oy = round((size - w) / 2), round(size - h - (size - 1.38 * h) / 2)
    cr.save()
    cr.set_antialias(cairo.ANTIALIAS_NONE)
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch != " ":
                cr.set_source_rgb(*(OUTLINE if ch == "#" else TEXT))
                cr.rectangle(ox + c * px, oy + r * px, px, px)
                cr.fill()
    cr.restore()
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


def mark(size):
    area = Gtk.DrawingArea(content_width=size, content_height=size, valign=Gtk.Align.CENTER)
    area.set_draw_func(lambda _a, cr, w, h: draw_mark(cr, min(w, h)))
    area.update_property([Gtk.AccessibleProperty.LABEL], ["Flippy"])
    return area


def headerbar(title):
    bar = Gtk.HeaderBar()
    bar.set_title_widget(Gtk.Label(label=title, css_classes=["title"]))
    return bar
