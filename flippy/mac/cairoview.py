"""Cairo drawing inside AppKit views: rasterize at the backing scale and blit as a CGImage."""
import math

import cairo
import objc
from AppKit import NSGraphicsContext, NSView
from Foundation import NSData
from Quartz import (CGColorSpaceCreateWithName, CGContextDrawImage, CGContextRestoreGState, CGContextSaveGState,
                    CGContextScaleCTM, CGContextTranslateCTM, CGDataProviderCreateWithCFData, CGImageCreate,
                    CGRectMake, kCGBitmapByteOrder32Little, kCGColorSpaceSRGB, kCGImageAlphaPremultipliedFirst,
                    kCGRenderingIntentDefault)

_SRGB = CGColorSpaceCreateWithName(kCGColorSpaceSRGB)


def blit(paint, w, h, scale, clip_to_ink=False):
    """Run paint(cr) for a w x h (logical px) flipped view and draw it into the current NSGraphicsContext.

    clip_to_ink: record first and rasterize only the painted area (cheap for a mostly
    empty full-screen overlay).
    """
    if clip_to_ink:
        rec = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
        paint(cairo.Context(rec))
        ix, iy, iw, ih = rec.ink_extents()
        if iw <= 0 or ih <= 0:
            return
        x0, y0 = max(math.floor(ix), 0), max(math.floor(iy), 0)
        x1, y1 = min(math.ceil(ix + iw) + 1, w), min(math.ceil(iy + ih) + 1, h)
        if x1 <= x0 or y1 <= y0:
            return
    else:
        rec, x0, y0, x1, y1 = None, 0, 0, w, h
    pw, ph = max(int(math.ceil((x1 - x0) * scale)), 1), max(int(math.ceil((y1 - y0) * scale)), 1)
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, pw, ph)
    cr = cairo.Context(img)
    cr.scale(scale, scale)
    cr.translate(-x0, -y0)
    if rec is not None:
        cr.set_source_surface(rec, 0, 0)
        cr.paint()
    else:
        paint(cr)
    img.flush()
    data = NSData.dataWithBytes_length_(bytes(img.get_data()), img.get_stride() * ph)
    cg = CGImageCreate(pw, ph, 8, 32, img.get_stride(), _SRGB,
                       kCGImageAlphaPremultipliedFirst | kCGBitmapByteOrder32Little,  # = cairo's ARGB32
                       CGDataProviderCreateWithCFData(data), None, False, kCGRenderingIntentDefault)
    ctx = NSGraphicsContext.currentContext().CGContext()
    CGContextSaveGState(ctx)
    CGContextTranslateCTM(ctx, x0, y1)  # the view is flipped; CGImages draw bottom-up
    CGContextScaleCTM(ctx, 1, -1)
    CGContextDrawImage(ctx, CGRectMake(0, 0, x1 - x0, y1 - y0), cg)
    CGContextRestoreGState(ctx)


class CairoView(NSView):
    """A view painted by draw(cr, w, h). Optional on_press(x, y, right), on_drag(x, y), on_release()."""

    def isFlipped(self):
        return True

    def acceptsFirstMouse_(self, event):
        return True

    def drawRect_(self, rect):
        b = self.bounds()
        w, h = b.size.width, b.size.height
        scale = self.window().backingScaleFactor() if self.window() else 2.0
        blit(lambda cr: self.draw(cr, w, h), w, h, scale)

    @objc.python_method
    def _pt(self, event):
        p = self.convertPoint_fromView_(event.locationInWindow(), None)
        return p.x, p.y

    @objc.python_method
    def _call(self, name, *args):
        fn = getattr(self, name, None)
        if fn:
            fn(*args)

    def mouseDown_(self, event):
        right = bool(event.modifierFlags() & (1 << 18))  # ctrl-click = right-click
        self._call("on_press", *self._pt(event), right)

    def rightMouseDown_(self, event):
        self._call("on_press", *self._pt(event), True)

    def mouseDragged_(self, event):
        self._call("on_drag", *self._pt(event))

    def rightMouseDragged_(self, event):
        self._call("on_drag", *self._pt(event))

    def mouseUp_(self, event):
        self._call("on_release")

    def rightMouseUp_(self, event):
        self._call("on_release")


def cairo_view(frame, draw, **handlers):
    v = CairoView.alloc().initWithFrame_(frame)
    v.draw = draw
    for k, fn in handlers.items():
        setattr(v, k, fn)
    return v

