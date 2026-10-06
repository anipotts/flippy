"""Main-loop timers, the same API on both platforms (GLib's semantics).

timeout_add(ms, fn, *args): fn runs on the main thread every ms until it returns
something falsy. idle_add(fn) runs fn once on the main thread soon; it's safe to
call from any thread. Both return an id for source_remove.
"""
import sys

if sys.platform == "darwin":
    from .mac.loop import idle_add, source_remove, timeout_add  # noqa: F401
else:
    from gi.repository import GLib

    timeout_add = GLib.timeout_add
    idle_add = GLib.idle_add
    source_remove = GLib.source_remove


def timeout_add_seconds(s, fn, *args):
    return timeout_add(int(s * 1000), fn, *args)
