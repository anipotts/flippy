"""GLib-style timers on the Cocoa run loop (see flippy/loop.py)."""
import itertools
import threading

from Foundation import NSRunLoop, NSRunLoopCommonModes, NSTimer
from PyObjCTools import AppHelper

_ids = itertools.count(1)
_timers = {}  # id -> NSTimer
_lock = threading.Lock()
_GONE = object()


def timeout_add(ms, fn, *args):
    sid = next(_ids)

    def fire(timer):
        if sid not in _timers:
            return
        try:
            again = fn(*args)
        except Exception:
            again = False
            import traceback
            traceback.print_exc()
        if not again:
            source_remove(sid)

    def schedule():
        # common modes: keep firing while a menu is open or the mouse is dragging
        t = NSTimer.timerWithTimeInterval_repeats_block_(ms / 1000, True, fire)
        with _lock:
            if sid not in _timers:  # removed before it got scheduled
                return
            _timers[sid] = t
        NSRunLoop.mainRunLoop().addTimer_forMode_(t, NSRunLoopCommonModes)

    with _lock:
        _timers[sid] = None
    if threading.current_thread() is threading.main_thread():
        schedule()
    else:
        AppHelper.callAfter(schedule)
    return sid


def idle_add(fn, *args):
    sid = next(_ids)
    with _lock:
        _timers[sid] = None

    def run():
        with _lock:
            if _timers.pop(sid, _GONE) is _GONE:  # removed
                return
        try:
            fn(*args)
        except Exception:
            import traceback
            traceback.print_exc()
    AppHelper.callAfter(run)
    return sid


def source_remove(sid):
    with _lock:
        t = _timers.pop(sid, None)
    if t is not None:
        t.invalidate()
