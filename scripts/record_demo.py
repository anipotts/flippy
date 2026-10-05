"""Record a scripted demo of flippy via the ScreenCast portal (PipeWire -> GStreamer -> ffmpeg).

Needs: gstreamer1.0-pipewire, ffmpeg. COSMIC asks once which screen to share.
Run:  python3 scripts/record_demo.py [out.mp4]
"""
import os
import secrets
import signal
import socket
import subprocess
import sys
import time

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "demo.mp4")
SOCK = os.path.join(os.environ["XDG_RUNTIME_DIR"], "flippy.sock")

# (seconds to wait after, flippy command); None = narration-free pause
SCRIPT = [
    (1.5, None),
    (14, "demo-type where do I change the wifi network?"),
    (11, "demo-type and where's bluetooth?"),
    (1.5, "dismiss"),
    (18, "demo-draw 1280 1392 400 46 what are these apps?"),  # circle the dock, then ask
    (1.5, "dismiss"),
]

DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
portal = bus.get_object("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
cast = dbus.Interface(portal, "org.freedesktop.portal.ScreenCast")
sender = bus.get_unique_name()[1:].replace(".", "_")


def request(method, *args, options=None):
    token = "flippy_" + secrets.token_hex(6)
    path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
    loop, out = GLib.MainLoop(), {}

    def on_response(code, results):
        out["code"], out["results"] = int(code), results
        loop.quit()
    match = bus.add_signal_receiver(on_response, "Response", "org.freedesktop.portal.Request", path=path)
    getattr(cast, method)(*args, dict(options or {}, handle_token=token))
    loop.run()
    match.remove()
    if out["code"] != 0:
        sys.exit(f"{method} failed/cancelled (code {out['code']})")
    return out["results"]


def flippy(cmd):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(SOCK)
        s.sendall((cmd + "\n").encode())
        s.recv(64)


def main():
    subprocess.run([os.path.expanduser("~/.local/bin/flippy-ask"), "start"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([os.path.expanduser("~/.local/bin/flippy-ask"), "dismiss"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    session = request("CreateSession", options={"session_handle_token": "flippy_s" + secrets.token_hex(4)})
    session = session["session_handle"]
    request("SelectSources", session, options={"types": dbus.UInt32(1), "multiple": False,
                                                "cursor_mode": dbus.UInt32(2)})  # 2 = cursor embedded
    started = request("Start", session, "")
    node_id = int(started["streams"][0][0])
    fd = cast.OpenPipeWireRemote(session, dbus.Dictionary({}, signature="sv")).take()
    print(f"recording node {node_id}", flush=True)

    webm = OUT.rsplit(".", 1)[0] + ".raw.webm"
    gst = subprocess.Popen(
        ["gst-launch-1.0", "-e",
         "pipewiresrc", f"fd={fd}", f"path={node_id}", "do-timestamp=true", "keepalive-time=1000", "always-copy=true",
         "!", "videoconvert", "!", "videoscale", "!", "video/x-raw,width=1920,height=1080",
         "!", "videorate", "!", "video/x-raw,framerate=30/1",
         "!", "vp8enc", "deadline=1", "cpu-used=8", "threads=4", "target-bitrate=12000000",
         "!", "webmmux", "!", "filesink", f"location={webm}"],
        pass_fds=(fd,), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    time.sleep(1.5)

    try:
        for wait, cmd in SCRIPT:
            if cmd:
                print("->", cmd, flush=True)
                flippy(cmd)
            time.sleep(wait)
    finally:
        gst.send_signal(signal.SIGINT)  # -e: send EOS so the file is finalized
        try:
            gst.wait(timeout=20)
        except subprocess.TimeoutExpired:
            gst.kill()
        err = gst.stderr.read().decode()
        if gst.returncode not in (0, None) and not os.path.exists(webm):
            sys.exit(f"gstreamer failed:\n{err[-2000:]}")

    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", webm, "-c:v", "libx264", "-preset", "medium",
                    "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", OUT], check=True)
    os.unlink(webm)
    print(f"saved {OUT}")


main()
