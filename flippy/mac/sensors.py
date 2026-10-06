"""Help mode's signals on macOS (see flippy/watch.py). All cheap, all local.

- frontmost app: NSWorkspace (no permission)
- idle seconds and input event count: CGEventSource counters, which count events
  without seeing them, so no Input Monitoring / Accessibility permission and no keylogging
- screen thumbnail: a 64x40 grayscale CGDisplayCreateImage (Screen Recording, which
  Flippy already has); the menu bar strip is cut off so its clock doesn't count as change
- the frontmost app's windows: CGWindowListCopyWindowInfo ids and bounds (no permission)
"""
import os
import time

import Quartz
from AppKit import NSWorkspace

from ..watch import Sample

THUMB_W, THUMB_H = 64, 40
MENU_BAR_FRAC = 0.04
_SELF = os.getpid()
_GRAY = Quartz.CGColorSpaceCreateDeviceGray()


def frontmost():
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return None, None, None
    return str(app.bundleIdentifier() or app.localizedName()), str(app.localizedName()), app.processIdentifier()


def thumbnail():
    """The main display as THUMB_W x THUMB_H grayscale values in 0-1, or None."""
    img = Quartz.CGDisplayCreateImage(Quartz.CGMainDisplayID())
    if img is None:
        return None
    w, h = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
    cut = int(h * MENU_BAR_FRAC)
    img = Quartz.CGImageCreateWithImageInRect(img, Quartz.CGRectMake(0, cut, w, h - cut))
    ctx = Quartz.CGBitmapContextCreate(None, THUMB_W, THUMB_H, 8, THUMB_W, _GRAY, Quartz.kCGImageAlphaNone)
    Quartz.CGContextSetInterpolationQuality(ctx, Quartz.kCGInterpolationLow)
    Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(0, 0, THUMB_W, THUMB_H), img)
    data = Quartz.CGBitmapContextGetData(ctx)
    raw = bytes(data.as_buffer(THUMB_W * THUMB_H))
    return [b / 255 for b in raw]


def windows(pid):
    """[(window id, (x, y, w, h))] of pid's normal on-screen windows, largest first."""
    info = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
    out = []
    for win in info or []:
        if win.get("kCGWindowOwnerPID") != pid or win.get("kCGWindowLayer", 0) != 0:
            continue
        b = win.get("kCGWindowBounds") or {}
        out.append((int(win["kCGWindowNumber"]), (b.get("X", 0), b.get("Y", 0), b.get("Width", 0), b.get("Height", 0))))
    return sorted(out, key=lambda w: -w[1][2] * w[1][3])


def sample(want_thumb=True):
    app, name, pid = frontmost()
    if pid == _SELF:  # our own windows (settings, the prompt) aren't the app being learned
        return Sample(time.monotonic(), None)
    st, anyev = Quartz.kCGEventSourceStateHIDSystemState, Quartz.kCGAnyInputEventType
    return Sample(
        t=time.monotonic(), app=app, app_name=name,
        idle_s=Quartz.CGEventSourceSecondsSinceLastEventType(st, anyev),
        events=Quartz.CGEventSourceCounterForEventType(st, anyev),
        thumb=thumbnail() if want_thumb else None,
        windows=windows(pid) if pid else None,
    )
