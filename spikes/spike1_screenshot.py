"""Spike 1: non-interactive screenshot via org.freedesktop.portal.Screenshot.

Prints the resulting file path, size and how long the portal round-trip took.
Run it a few times to see whether COSMIC prompts every time, once, or never.

Run:  python3 spikes/spike1_screenshot.py [copy-to-path]
"""
import secrets
import shutil
import sys
import time
from urllib.parse import unquote, urlparse

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
portal = bus.get_object("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
screenshot_iface = dbus.Interface(portal, "org.freedesktop.portal.Screenshot")

loop = GLib.MainLoop()
result = {}

# Subscribe to the Request's Response signal *before* calling, using the
# predictable handle path, so a fast response can't be missed.
token = "flippy_" + secrets.token_hex(6)
sender = bus.get_unique_name()[1:].replace(".", "_")
handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"


def on_response(code, results):
    result["code"] = int(code)
    result["uri"] = str(results.get("uri", ""))
    loop.quit()


bus.add_signal_receiver(on_response, signal_name="Response",
                        dbus_interface="org.freedesktop.portal.Request", path=handle)

t0 = time.monotonic()
returned = screenshot_iface.Screenshot("", {"handle_token": token, "interactive": False, "modal": False})
if str(returned) != handle:
    # older portals ignore handle_token; subscribe to the path it actually gave us
    bus.add_signal_receiver(on_response, signal_name="Response",
                            dbus_interface="org.freedesktop.portal.Request", path=str(returned))
GLib.timeout_add_seconds(30, lambda: (result.setdefault("code", -1), loop.quit()))
loop.run()
dt = time.monotonic() - t0

if result.get("code") != 0:
    sys.exit(f"portal failed: response code {result.get('code')} (1=cancelled, 2=other, -1=timeout)")

path = unquote(urlparse(result["uri"]).path)
from gi.repository import GdkPixbuf  # noqa: E402  (just to read dimensions without PIL)
fmt, w, h = GdkPixbuf.Pixbuf.get_file_info(path)
print(f"ok in {dt:.2f}s: {path}  {w}x{h}")
if len(sys.argv) > 1:
    shutil.copy(path, sys.argv[1])
    print(f"copied to {sys.argv[1]}")
