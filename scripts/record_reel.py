"""Record the footage for the reel (scripts/edit_reel.py): Blender + Firefox scenes, theme and
pointer montages, settings. Same output layout as record_raw.py.

Blender should already be open on scripts/demo_blender_scene.py. FIREFOX_PROFILE (env) is a
throwaway profile dir; Firefox is launched on the painting for the draw scene and closed after.

Original docstring:
Record a scripted flippy session at full resolution, with wall-clock timestamps per frame.

Frames land in <outdir>/frames/<unix_time>.jpg and the daemon's UI events are
copied to <outdir>/events.jsonl, so scripts/edit_demo.py can cut and zoom in sync.

Needs gstreamer1.0-pipewire. COSMIC asks once which screen to share.
Run:  python3 scripts/record_reel.py <outdir> [retake]
"""
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time

import dbus
import gi
from dbus.mainloop.glib import DBusGMainLoop

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402

OUTDIR = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "reel_raw")
FIREFOX_PROFILE = os.environ.get("FIREFOX_PROFILE", "")
PAINTING = "https://upload.wikimedia.org/wikipedia/commons/a/a5/Tsunami_by_hokusai_19th_century.jpg"
SOCK = os.path.join(os.environ["XDG_RUNTIME_DIR"], "flippy.sock")
EVENTS = os.path.join(os.environ["XDG_RUNTIME_DIR"], "flippy-events.jsonl")
FLIPPY_ASK = os.path.expanduser("~/.local/bin/flippy-ask")

# Scenes: ("cmd", <socket command>) | ("wait", s) | ("until", event, extra_s, timeout) | ("mark", name) | ("sh", argv)
THEMES = ["midnight", "y2k", "glass", "terminal", "cosmic"]
POINTERS = ["hand", "ring", "arrow", "dot", "custom:My pointer"]
SCENES = [
    ("cmd", "set look.theme glass"), ("cmd", "set look.pointer theme"),
    ("wait", 1.5),
    ("mark", "ask"),
    ("cmd", "demo-type how do I make the ring glow purple?"),
    ("until", "answer_done", 4.0, 60),
    ("cmd", "dismiss"), ("wait", 1.0),
    ("cmd", "set look.theme y2k"),
    ("mark", "tour"),
    ("cmd", "demo-type walk me through rendering this to an image"),
    ("until", "answer_done", 4.0, 90),
    ("cmd", "dismiss"), ("wait", 1.0),
    ("mark", "themes"),
]
for th in THEMES:
    SCENES += [("cmd", f"set look.theme {th}"), ("mark", f"theme:{th}"), ("cmd", "preview"), ("wait", 4.0),
               ("cmd", "dismiss"), ("wait", 0.6)]
SCENES += [("cmd", "set look.theme midnight"), ("mark", "pointers")]
for p in POINTERS:
    SCENES += [("cmd", f"set look.pointer {p}"), ("mark", f"pointer:{p}"), ("cmd", "preview"), ("wait", 3.0),
               ("cmd", "dismiss"), ("wait", 0.6)]
SCENES += [
    ("cmd", "set look.pointer theme"), ("cmd", "set look.theme terminal"),
    ("sh", ["firefox", "--no-remote", "--new-instance", "--profile", FIREFOX_PROFILE, PAINTING]),
    ("wait", 8.0),
    ("mark", "draw"),
    ("cmd", "demo-draw 430 400 70 160 what does this say?"),
    ("until", "answer_done", 4.0, 90),
    ("cmd", "dismiss"), ("wait", 1.0),
    ("sh", ["pkill", "-f", "--", f"profile {FIREFOX_PROFILE}"]),
    ("wait", 2.0),
    ("cmd", "set look.theme glass"),
    ("mark", "settings"),
    ("cmd", "settings"),
    ("wait", 5.0),
]
# `record_reel.py <outdir> retake`: the walkthrough again (after an ask, which is what used to trip the
# early-fade bug) and the pointer editor.
RETAKE = [
    ("cmd", "set look.theme glass"), ("cmd", "set look.pointer theme"), ("wait", 1.5),
    ("mark", "ask"),
    ("cmd", "demo-type how do I make the ring glow purple?"),
    ("until", "answer_done", 4.0, 60),
    ("cmd", "dismiss"), ("wait", 1.0),
    ("cmd", "set look.theme y2k"),
    ("mark", "tour"),
    ("cmd", "demo-type walk me through rendering this to an image"),
    ("until", "answer_done", 5.0, 90),
    ("cmd", "dismiss"), ("wait", 1.5),
    ("cmd", "set look.theme glass"),
    ("mark", "editor"),
    ("cmd", "demo-pointer Sunset"),
    ("until", "cleared", 1.0, 40),
    ("cmd", "set look.pointer theme"),
]
if len(sys.argv) > 2 and sys.argv[2] == "retake":
    SCENES = RETAKE


def flippy(cmd):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(SOCK)
        s.sendall((cmd + "\n").encode())
        s.recv(64)


def events_since(t0):
    try:
        with open(EVENTS) as f:
            return [e for e in map(json.loads, f) if e["t"] >= t0]
    except FileNotFoundError:
        return []


def portal_stream():
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
        m = bus.add_signal_receiver(on_response, "Response", "org.freedesktop.portal.Request", path=path)
        getattr(cast, method)(*args, dict(options or {}, handle_token=token))
        loop.run()
        m.remove()
        if out["code"] != 0:
            sys.exit(f"{method} failed/cancelled (code {out['code']})")
        return out["results"]

    session = request("CreateSession", options={"session_handle_token": "flippy_s" + secrets.token_hex(4)})
    session = session["session_handle"]
    request("SelectSources", session, options={"types": dbus.UInt32(1), "multiple": False,
                                                "cursor_mode": dbus.UInt32(2)})
    started = request("Start", session, "")
    node = int(started["streams"][0][0])
    fd = cast.OpenPipeWireRemote(session, dbus.Dictionary({}, signature="sv")).take()
    return fd, node


def main():
    frames_dir = os.path.join(OUTDIR, "frames")
    shutil.rmtree(OUTDIR, ignore_errors=True)
    os.makedirs(frames_dir)
    subprocess.run([FLIPPY_ASK, "start"], stdout=subprocess.DEVNULL)
    subprocess.run([FLIPPY_ASK, "dismiss"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    fd, node = portal_stream()
    Gst.init(None)
    pipe = Gst.parse_launch(
        f"pipewiresrc fd={fd} path={node} always-copy=true ! videoconvert ! "
        "queue leaky=downstream max-size-buffers=3 ! jpegenc quality=92 ! "
        "appsink name=sink emit-signals=true sync=false max-buffers=8 drop=true")
    count = {"n": 0}

    def on_sample(sink):
        buf = sink.emit("pull-sample").get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if ok:
            with open(os.path.join(frames_dir, f"{time.time():.4f}.jpg"), "wb") as f:
                f.write(info.data)
            buf.unmap(info)
            count["n"] += 1
        return Gst.FlowReturn.OK
    pipe.get_by_name("sink").connect("new-sample", on_sample)
    pipe.set_state(Gst.State.PLAYING)
    loop = GLib.MainLoop()
    marks = []

    def run_scenes():
        time.sleep(1.0)
        t_start = time.time()
        try:
            for step in SCENES:
                kind = step[0]
                if kind == "wait":
                    time.sleep(step[1])
                elif kind == "mark":
                    marks.append({"t": time.time(), "scene": step[1]})
                elif kind == "sh":
                    subprocess.Popen(step[1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
                elif kind == "cmd":
                    print("->", step[1], flush=True)
                    flippy(step[1])
                elif kind == "until":
                    _, name, extra, timeout = step
                    t0 = time.time()
                    while time.time() - t0 < timeout:
                        if any(e["ev"] == name for e in events_since(t0)):
                            break
                        time.sleep(0.2)
                    else:
                        print(f"timed out waiting for {name}", flush=True)
                    time.sleep(extra)
        finally:
            with open(os.path.join(OUTDIR, "events.jsonl"), "w") as f:
                for e in events_since(t_start - 1):
                    f.write(json.dumps(e) + "\n")
            with open(os.path.join(OUTDIR, "marks.json"), "w") as f:
                json.dump(marks, f)
            GLib.idle_add(loop.quit)

    threading.Thread(target=run_scenes, daemon=True).start()
    loop.run()
    pipe.set_state(Gst.State.NULL)
    print(f"{count['n']} frames -> {frames_dir}")


main()
