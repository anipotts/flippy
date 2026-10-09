"""Text layout for the themes on macOS: cairo's Quartz fonts instead of Pango.

Implements the small slice of Pango the themes use: a layout with an optional
wrap width (word wrap, breaking long words), END ellipsizing, pixel extents
and drawing. Linux font names are mapped to their closest macOS fonts.
"""
import os

import cairo
from Foundation import NSURL
from CoreText import CTFontManagerRegisterFontsForURL, kCTFontManagerScopeProcess

FONTS = {"Noto Sans": "Helvetica Neue", "Fira Sans": "Helvetica Neue", "Fira Mono": "Menlo"}
# cairo's toy font API draws with one font and no fallback, so characters the theme's font lacks (arrows, ✓, ⌘,
# ∗, ★, CJK, emoji: Helvetica Neue has none of these) came out as boxes. Those characters are drawn with the first
# of these that has them; all ship with macOS.
FALLBACKS = ("Arial Unicode MS", "Apple Symbols", "Menlo", "Apple Color Emoji")
ELLIPSIS = "…"


def load_fonts(font_dir):
    """Register bundled fonts for this process only (nothing installed system-wide)."""
    for f in os.listdir(font_dir):
        if f.endswith((".ttf", ".otf")):
            CTFontManagerRegisterFontsForURL(NSURL.fileURLWithPath_(os.path.join(font_dir, f)),
                                             kCTFontManagerScopeProcess, None)


class Layout:
    def __init__(self, cr, text, family, px, width=None, bold=False):
        weight = cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL
        self.face = cairo.ToyFontFace(FONTS.get(family, family), cairo.FONT_SLANT_NORMAL, weight)
        self.faces = [self.face] + [_face(name, weight) for name in FALLBACKS]
        self.px = px
        self.text = text
        self.width = width
        self.ellipsize = False
        self._lines = None
        self._ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
        self._apply(self._ctx)
        self.ascent, self.descent, self.line_h = self._ctx.font_extents()[:3]

    def _apply(self, cr):
        cr.set_font_face(self.face)
        cr.set_font_size(self.px)

    def _runs(self, s):
        """[(face, text)]: s split where the font that can draw it changes."""
        runs = []
        for ch in s:
            face = self.face if ch in " \t" else next((f for f in self.faces if _has(f, ch, self.px)), self.face)
            if runs and runs[-1][0] is face:
                runs[-1][1] += ch
            else:
                runs.append([face, ch])
        return runs

    def _w(self, s):
        width = 0
        for face, text in self._runs(s):
            self._ctx.set_font_face(face)
            width += self._ctx.text_extents(text).x_advance
        self._ctx.set_font_face(self.face)
        return width

    def set_ellipsize(self, on=True):
        self.ellipsize = on
        self._lines = None

    def lines(self):
        if self._lines is None:
            out = []
            for para in self.text.split("\n"):
                if not self.width:
                    out.append(para)
                elif self.ellipsize:
                    out.append(self._ellipsized(para))
                else:
                    out.extend(self._wrap(para))
            self._lines = out
        return self._lines

    def _ellipsized(self, s):
        if self._w(s) <= self.width:
            return s
        while s and self._w(s + ELLIPSIS) > self.width:
            s = s[:-1]
        return s.rstrip() + ELLIPSIS

    def _wrap(self, para):
        lines, cur = [], ""
        for word in para.split(" "):
            cand = f"{cur} {word}" if cur else word
            if self._w(cand) <= self.width:
                cur = cand
                continue
            if cur:
                lines.append(cur)
                cur = ""
            while self._w(word) > self.width and len(word) > 1:  # break a word that can't fit on a line
                k = len(word) - 1
                while k > 1 and self._w(word[:k]) > self.width:
                    k -= 1
                lines.append(word[:k])
                word = word[k:]
            cur = word
        lines.append(cur)
        return lines

    def size(self):
        lines = self.lines()
        return max((self._w(ln) for ln in lines), default=0), self.line_h * len(lines)

    def show(self, cr, x, y):
        cr.save()
        self._apply(cr)
        for i, ln in enumerate(self.lines()):
            cr.move_to(x, y + self.ascent + i * self.line_h)
            for face, text in self._runs(ln):
                cr.set_font_face(face)
                cr.show_text(text)  # advances the current point to where the next run starts
        cr.restore()


_FACES = {}
_HAS = {}
_PROBE = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))


def _face(name, weight):
    key = (name, weight)
    if key not in _FACES:
        _FACES[key] = cairo.ToyFontFace(name, cairo.FONT_SLANT_NORMAL, weight)
    return _FACES[key]


def _has(face, ch, px):
    """Does this font have a glyph for ch (glyph 0 is "missing")? Cached per font and character."""
    key = (id(face), ch)
    if key not in _HAS:
        _PROBE.set_font_face(face)
        _PROBE.set_font_size(px or 16)
        glyphs = _PROBE.get_scaled_font().text_to_glyphs(0, 0, ch, False)
        _HAS[key] = bool(glyphs) and all(g[0] != 0 for g in glyphs)
    return _HAS[key]
