"""gtk4-layer-shell's LD_PRELOAD (bin/flippy-daemon sets it), kept out of everything Flippy starts.

The loader reads LD_PRELOAD once, at the daemon's start, so once it's running the entry is only something every
child would inherit: apps /act opens, login terminals, xdg-open, the Claude CLI. No GTK here, so it's testable.
"""
import os
import re

LIB = "libgtk4-layer-shell.so"


def without_layer_shell(value):
    """LD_PRELOAD minus gtk4-layer-shell's entry (the loader splits it on colons and spaces); None if nothing's
    left."""
    keep = [p for p in re.split(r"[:\s]+", value or "") if p and not os.path.basename(p).startswith(LIB)]
    return ":".join(keep) or None


def scrub(env=os.environ):
    """Take gtk4-layer-shell out of env's LD_PRELOAD (the daemon's own, by default), leaving any others."""
    if LIB not in env.get("LD_PRELOAD", ""):
        return
    rest = without_layer_shell(env["LD_PRELOAD"])
    if rest is None:
        del env["LD_PRELOAD"]
    else:
        env["LD_PRELOAD"] = rest
