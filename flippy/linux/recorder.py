"""Demo recording on COSMIC (flippy-ask record start <path> | record stop): the ScreenCast portal into GStreamer.

The portal asks which screen to share the first time; its restore token is kept in
~/.config/flippy/screencast-token so later recordings start without asking. Frames
come over PipeWire (pipewiresrc) and are encoded with openh264 into .mp4, .mov or
.mkv (by the path's extension). Like the macOS version, stopping writes
<path>.json with the wall clock at stop.
"""
import json
import os
import secrets
import signal
import subprocess
import threading
import time

import dbus

from .. import settings

PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
CAST_IFACE = "org.freedesktop.portal.ScreenCast"
TOKEN_PATH = os.path.join(os.path.dirname(settings.PATH), "screencast-token")
MONITOR, CURSOR_EMBEDDED, PERSIST_UNTIL_REVOKED = 1, 2, 2
MUXERS = {".mov": "qtmux", ".mkv": "matroskamux"}  # else mp4mux


def log(*a):
    print("flippy: record:", *a, flush=True)


class Recorder:
    def __init__(self, bus):
        self.bus = bus
        self.portal = dbus.Interface(bus.get_object(PORTAL, PORTAL_PATH), CAST_IFACE)
        self.session = None
        self.proc = None
        self.path = None
        self.matches = []

    # ---- portal requests: each answers with a Response signal on its own request path
    def _request(self, method, args, options, on_ok):
        token = "flippy_" + secrets.token_hex(6)
        sender = self.bus.get_unique_name()[1:].replace(".", "_")
        handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        options = dict(options, handle_token=token)

        def on_response(code, results):
            for m in self.matches:
                m.remove()
            self.matches = []
            if int(code) != 0:
                log(f"{method} {'cancelled' if int(code) == 1 else 'failed'} ({int(code)})")
                self._close_session()
                return
            on_ok(results)
        self.matches.append(self.bus.add_signal_receiver(on_response, signal_name="Response",
                                                         dbus_interface="org.freedesktop.portal.Request", path=handle))
        getattr(self.portal, method)(*args, dbus.Dictionary(options, signature="sv"),
                                     reply_handler=lambda *r: None, error_handler=lambda e: log(f"{method}: {e}"))

    def start(self, path):
        self.stop()
        self.path = path
        self._request("CreateSession", (), {"session_handle_token": "flippy_" + secrets.token_hex(6)},
                      self._created)

    def _created(self, results):
        self.session = dbus.ObjectPath(str(results["session_handle"]))
        props = dbus.Interface(self.bus.get_object(PORTAL, PORTAL_PATH), "org.freedesktop.DBus.Properties")
        options = {"types": dbus.UInt32(MONITOR), "multiple": False, "persist_mode": dbus.UInt32(PERSIST_UNTIL_REVOKED)}
        try:
            if int(props.Get(CAST_IFACE, "AvailableCursorModes")) & CURSOR_EMBEDDED:
                options["cursor_mode"] = dbus.UInt32(CURSOR_EMBEDDED)  # the real cursor, like screencapture -C
        except dbus.DBusException:
            pass
        try:
            with open(TOKEN_PATH) as f:
                options["restore_token"] = f.read().strip()
        except OSError:
            pass
        self._request("SelectSources", (self.session,), options, self._selected)

    def _selected(self, _results):
        self._request("Start", (self.session, ""), {}, self._started)

    def _started(self, results):
        token = results.get("restore_token")
        if token:
            os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
            with open(TOKEN_PATH, "w") as f:
                f.write(str(token))
        streams = results.get("streams") or []
        if not streams:
            log("the portal gave no stream")
            self._close_session()
            return
        node = int(streams[0][0])
        fd = self.portal.OpenPipeWireRemote(self.session, dbus.Dictionary({}, signature="sv")).take()
        mux = MUXERS.get(os.path.splitext(self.path)[1].lower(), "mp4mux")
        pipeline = (f"pipewiresrc fd={fd} path={node} do-timestamp=true keepalive-time=1000 ! videoconvert ! "
                    f"videorate ! video/x-raw,framerate=30/1 ! openh264enc bitrate=16000000 ! h264parse ! {mux} ! "
                    f"filesink location={self.path}")
        self.proc = subprocess.Popen(["gst-launch-1.0", "-e", *pipeline.split()], pass_fds=(fd,),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        os.close(fd)
        log(f"recording to {self.path}")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            stopped = time.time()
            proc, path = self.proc, self.path
            proc.send_signal(signal.SIGINT)  # -e: turns into end-of-stream, so the file gets finished

            def finish():  # off the main thread: finishing the file can take a while
                try:
                    proc.wait(30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                with open(path + ".json", "w") as f:
                    json.dump({"stopped": stopped}, f)
                log(f"saved {path}")
            threading.Thread(target=finish, daemon=True).start()
        elif self.proc and self.proc.returncode:
            log(f"gst-launch failed: {self.proc.stderr.read().decode(errors='replace')[-500:]}")
        self.proc = None
        self._close_session()

    def _close_session(self):
        if self.session:
            try:
                dbus.Interface(self.bus.get_object(PORTAL, self.session), "org.freedesktop.portal.Session").Close()
            except dbus.DBusException:
                pass
            self.session = None
