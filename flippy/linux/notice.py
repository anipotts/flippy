"""The small card in the overlay's top-right corner on COSMIC: help mode's "Need a hand?", tips, updates.

On macOS these are a panel of their own (flippy/mac/nudge.py). On COSMIC a
separate surface isn't an option (unmapping a layer surface drops the Wayland
connection, see flippy/linux/ui.py), so the card is painted into the overlay by
NoticeLayer, a mixin over the shared OverlayBase that leaves the shared painting
as it is and adds the card, its clickable buttons, and `ink`: where Flippy
painted this frame (the click watcher leaves those parts of the screen out).
"""
import time

from .. import settings, themes

NOTICE_TOP = 48             # under the panel
NOTICE_W, NOTICE_PAD = 320, 14
FONT = "Noto Sans"


class Notice:
    """Bold head, detail, a right-aligned row of buttons [(title, fn)] (the last is the primary one) and an
    optional small link (title, fn) under them."""

    def __init__(self, head, detail, buttons, link=None, width=None):
        self.head, self.detail, self.buttons, self.link = head, detail, buttons, link
        self.width = width or NOTICE_W

    def layout(self, cr, x, y):
        """(card rect, ((head layout, x, y), (detail layout, x, y)), {hit name: (rect, title)})."""
        width = self.width
        inner = width - 2 * NOTICE_PAD
        head = themes.layout(cr, self.head, FONT, 14, width=inner, bold=True)
        detail = themes.layout(cr, self.detail, FONT, 13, width=inner)
        hh, dh = themes.lsize(head)[1], themes.lsize(detail)[1]
        by = y + NOTICE_PAD + hh + 4 + dh + 12
        bh = 28
        rects = {}
        bx = x + width - NOTICE_PAD
        for i in reversed(range(len(self.buttons))):
            bw = themes.lsize(themes.layout(cr, self.buttons[i][0], FONT, 13))[0] + 24
            bx -= bw
            rects[f"notice:{i}"] = ((bx, by, bw, bh), self.buttons[i][0])
            bx -= 8
        h = by + bh - y + NOTICE_PAD
        if self.link:
            lw, lh = themes.lsize(themes.layout(cr, self.link[0], FONT, 12))
            rects["notice:link"] = ((x + NOTICE_PAD, by + bh + 6, lw, lh + 4), self.link[0])
            h += lh + 10
        return (x, y, width, h), ((head, x + NOTICE_PAD, y + NOTICE_PAD),
                                  (detail, x + NOTICE_PAD, y + NOTICE_PAD + hh + 4)), rects

    def callback(self, name):
        key = name.split(":", 1)[1]
        return self.link[1] if key == "link" else self.buttons[int(key)][1]


class NoticeLayer:
    """Mix in before OverlayBase. The platform's hits_changed() should do nothing while self.in_base_paint.

    Cards stack: the newest shows, and hiding it brings back the one it covered. A desktop task's approval card
    can come up over a tip, and the tip's own timer or buttons must not take the approval card down with it."""

    notices = ()              # Notice cards, newest last; the newest is the one on screen
    ink = ()                  # [(x, y, w, h)] painted this frame: pointer, card, notice
    in_base_paint = False

    @property
    def notice_card(self):
        return self.notices[-1] if self.notices else None

    def show_notice(self, notice):
        self.notices = [n for n in self.notices if n is not notice] + [notice]
        if (self.pressed[0] or "").startswith("notice:"):
            self.pressed = (None, 0.0)  # the last card's button, not this one's
        self.queue_draw()

    def hide_notice(self, notice=None):
        """Take that card down (all of them when None)."""
        left = [n for n in self.notices if notice is not None and n is not notice]
        if len(left) != len(self.notices):
            self.notices = left
            self.queue_draw()

    def notice_buttons(self):
        """{title (lowercase): hit name} of the card's buttons and link, for scripted presses."""
        n = self.notice_card
        if n is None:
            return {}
        out = {title.lower(): f"notice:{i}" for i, (title, _) in enumerate(n.buttons)}
        if n.link:
            out["link"] = "notice:link"
        return out

    def press_notice(self, name):
        if self.notice_card is None:
            return
        self.pressed = (name, time.monotonic())
        self.notice_card.callback(name)()

    # --- on top of OverlayBase
    def paint(self, cr, w, h):
        self.in_base_paint = True
        try:
            super().paint(cr, w, h)
        finally:
            self.in_base_paint = False
        ink = []
        if self.target and self.pos:
            right, left, below, above = themes.pointer_extent(self.pointer_style(), settings.get("look", "pointer_size"))
            px, py = self.pos
            ink.append((px - left - 24, py - above - 24, left + right + 48, above + below + 48))  # + bob and glow
        lay = self.card_layout(w, h)
        if lay:
            x, y, cw, ch = lay[0]
            ink.append((x - 16, y - 16, cw + 32, ch + 32))  # + shadow
        if self.notice_card:
            rect, hits = self._draw_notice(cr, w)
            self.hits = {**self.hits, **hits}
            ink.append(rect)
        self.ink = ink
        self.hits_changed()

    def press(self, x, y):
        if not self.drawing:
            name, _ = self._hit(x, y)
            if name and name.startswith("notice:"):
                self.press_notice(name)
                return
        super().press(x, y)

    def _draw_notice(self, cr, w):
        n = self.notice_card
        (x, y, nw, nh), texts, rects = n.layout(cr, w - n.width - 12, NOTICE_TOP)
        themes.round_rect(cr, x + 0.5, y + 0.5, nw - 1, nh - 1, 16)
        cr.set_source_rgba(0.08, 0.08, 0.1, 0.94)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.16)
        cr.set_line_width(1)
        cr.stroke()
        (head, hx, hy), (detail, dx, dy) = texts
        themes.show(cr, head, hx, hy, (1, 1, 1, 1))
        themes.show(cr, detail, dx, dy, (1, 1, 1, 0.8))
        pressed = self.pressed[0] if time.monotonic() - self.pressed[1] < 0.18 else None
        last = f"notice:{len(n.buttons) - 1}"
        for name, ((bx, by, bw, bh), title) in rects.items():
            lay = themes.layout(cr, title, FONT, 12 if name == "notice:link" else 13)
            tw, th = themes.lsize(lay)
            if name == "notice:link":
                themes.show(cr, lay, bx, by + 2, (1, 1, 1, 0.85 if pressed == name else 0.6))
                continue
            themes.round_rect(cr, bx, by, bw, bh, bh / 2)
            if name == last:
                cr.set_source_rgba(*self.theme.accent, 1.0 if pressed == name else 0.85)
            else:
                cr.set_source_rgba(1, 1, 1, 0.24 if pressed == name else 0.12)
            cr.fill()
            themes.show(cr, lay, bx + (bw - tw) / 2, by + (bh - th) / 2, (1, 1, 1, 1))
        return (x, y, nw, nh), {name: rect for name, (rect, _) in rects.items()}
