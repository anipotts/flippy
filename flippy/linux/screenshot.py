"""Non-interactive screenshot through xdg-desktop-portal (callback style, GLib main loop)."""
import os
import secrets
from urllib.parse import unquote, urlparse

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

DBusGMainLoop(set_as_default=True)

_REQ_IFACE = "org.freedesktop.portal.Request"


class Screenshotter:
    def __init__(self):
        self.bus = dbus.SessionBus()
        portal = self.bus.get_object("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
        self.iface = dbus.Interface(portal, "org.freedesktop.portal.Screenshot")

    def take(self, on_done, timeout_s=15):
        """Calls on_done(path, None) on success or on_done(None, error_str)."""
        token = "flippy_" + secrets.token_hex(6)
        sender = self.bus.get_unique_name()[1:].replace(".", "_")
        handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        state = {"done": False, "matches": []}

        def finish(path, err):
            if state["done"]:
                return
            state["done"] = True
            for m in state["matches"]:
                m.remove()
            on_done(path, err)

        def on_response(code, results):
            if int(code) != 0:
                finish(None, f"screenshot portal returned {int(code)}")
                return
            path = os.path.normpath(unquote(urlparse(str(results.get("uri", ""))).path))
            finish(path, None) if path and os.path.exists(path) else finish(None, "screenshot file missing")

        def listen(path):
            state["matches"].append(self.bus.add_signal_receiver(
                on_response, signal_name="Response", dbus_interface=_REQ_IFACE, path=path))

        listen(handle)

        def on_reply(returned):
            if str(returned) != handle:
                listen(str(returned))

        self.iface.Screenshot("", {"handle_token": token, "interactive": False, "modal": False},
                              reply_handler=on_reply, error_handler=lambda e: finish(None, str(e)))
        GLib.timeout_add_seconds(timeout_s, lambda: finish(None, "screenshot timed out") or False)

    def pick_color(self, on_done):
        """The Draw editor's eyedropper: the portal lets the user click anywhere on screen. on_done(rgb, failed):
        (r, g, b) 0-1 and False, or None and whether it failed (False: they cancelled). No timeout: picking takes as
        long as they like."""
        token = "flippy_" + secrets.token_hex(6)
        sender = self.bus.get_unique_name()[1:].replace(".", "_")
        handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        state = {"done": False, "matches": []}

        def finish(color, failed):
            if state["done"]:
                return
            state["done"] = True
            for m in state["matches"]:
                m.remove()
            on_done(color, failed)

        def listen(path):
            state["matches"].append(self.bus.add_signal_receiver(
                lambda code, results: finish(*picked_color(code, results)), signal_name="Response",
                dbus_interface=_REQ_IFACE, path=path))
        listen(handle)
        self.iface.PickColor("", {"handle_token": token},
                             reply_handler=lambda returned: str(returned) != handle and listen(str(returned)),
                             error_handler=lambda e: finish(None, True))


def picked_color(code, results):
    """A PickColor Response -> ((r, g, b) 0-1 or None, failed). Code 1 is the user cancelling, not a failure."""
    if int(code) != 0:
        return None, int(code) != 1
    try:
        r, g, b = (max(0.0, min(float(c), 1.0)) for c in results.get("color"))
    except (TypeError, ValueError):
        return None, True
    return (r, g, b), False
