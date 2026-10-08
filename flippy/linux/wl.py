"""What's going on in other apps, from COSMIC's Wayland protocols (help mode, tutorials that wait for clicks).

A second, private Wayland connection on its own thread, separate from GTK's, that
speaks just enough of the wire protocol for a few read-only protocols (no
pywayland, no generated bindings):

  ext_foreign_toplevel_list_v1 + zcosmic_toplevel_info_v1   app id, title, geometry, which one is active
  ext_idle_notifier_v1 (input idle)                         seconds since the last input, and a count of
                                                            idle -> busy flips (stands in for macOS's event count)
  ext_image_copy_capture_v1 (toplevel source)               a tiny grayscale thumbnail of the active window,
                                                            without the panel or Flippy's own overlay on it
  ext_image_copy_capture cursor session (output source)     where the mouse is, and how much it moves
  zwp_virtual_keyboard_v1                                   scripted typing (flippy-ask type/key/tap)

None of it needs a permission prompt on COSMIC. Anything the compositor doesn't
offer stays None, and the rules that need it switch off (see flippy/watch.py).
"""
import array
import mmap
import os
import select
import socket
import struct
import threading
import time

IDLE_MS = 2000              # "idle" after this long without input; each idle -> resumed flip counts as activity
SELF_APP_ID = "dev.flippy.daemon"

# wire opcodes (requests are sent, events received), from the protocol XML
WL_DISPLAY_SYNC, WL_DISPLAY_GET_REGISTRY = 0, 1
WL_REGISTRY_BIND = 0
WL_SEAT_GET_POINTER = 0
WL_SHM_CREATE_POOL = 0
WL_SHM_POOL_CREATE_BUFFER, WL_SHM_POOL_DESTROY = 0, 1
WL_BUFFER_DESTROY = 0
TOPLEVEL_INFO_GET_COSMIC_TOPLEVEL = 1
IDLE_GET_NOTIFICATION, IDLE_GET_INPUT_NOTIFICATION = 1, 2
CAPTURE_CREATE_SESSION, CAPTURE_CREATE_POINTER_CURSOR_SESSION = 0, 1
OUTPUT_SOURCE_CREATE, TOPLEVEL_SOURCE_CREATE = 0, 0
SOURCE_DESTROY = 0
SESSION_CREATE_FRAME, SESSION_DESTROY = 0, 1
FRAME_DESTROY, FRAME_ATTACH_BUFFER, FRAME_DAMAGE_BUFFER, FRAME_CAPTURE = 0, 1, 2, 3
CURSOR_SESSION_DESTROY = 0
VK_CREATE = 0
VK_KEYMAP, VK_KEY, VK_MODIFIERS = 0, 1, 2
KEYMAP_XKB_V1 = 1
COSMIC_STATE_ACTIVATED = 2
# wl_shm formats we can read, best first, with the byte order PIL calls them (little-endian memory)
SHM_FORMATS = ((0x34324258, "RGBX"), (0x34324241, "RGBA"), (1, "BGRX"), (0, "BGRA"))  # XB24, AB24, XR24, AR24

WANT = {  # interface: highest version we speak
    "wl_seat": 5, "wl_shm": 1, "wl_output": 1,
    "ext_foreign_toplevel_list_v1": 1, "zcosmic_toplevel_info_v1": 3, "ext_idle_notifier_v1": 2,
    "ext_image_copy_capture_manager_v1": 1, "ext_foreign_toplevel_image_capture_source_manager_v1": 1,
    "ext_output_image_capture_source_manager_v1": 1, "zwp_virtual_keyboard_manager_v1": 1,
}


class WaylandError(Exception):
    pass


def _string(s):
    b = s.encode() + b"\0"
    return struct.pack("<I", len(b)) + b + b"\0" * (-len(b) % 4)


class _Reader:
    def __init__(self, data):
        self.data, self.at = data, 0

    def u(self):
        v = struct.unpack_from("<I", self.data, self.at)[0]
        self.at += 4
        return v

    def i(self):
        v = struct.unpack_from("<i", self.data, self.at)[0]
        self.at += 4
        return v

    def s(self):
        n = self.u()
        v = self.data[self.at:self.at + n - 1].decode(errors="replace") if n else None
        self.at += (n + 3) & ~3
        return v

    def a(self):
        n = self.u()
        v = self.data[self.at:self.at + n]
        self.at += (n + 3) & ~3
        return v


class Toplevel:
    def __init__(self, ext_id):
        self.ext_id = ext_id        # ext_foreign_toplevel_handle_v1 (capture source needs it)
        self.cosmic_id = None
        self.app_id = self.title = None
        self.geometry = None        # (x, y, w, h), output-relative logical px
        self.activated = False
        self.serial = 0             # bumps when it appears, so "new window" can be told apart


class Wayland:
    """The connection and its thread. Read the public attributes from any thread; they're replaced, not mutated."""

    def __init__(self):
        path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), os.environ.get("WAYLAND_DISPLAY", "wayland-0"))
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.buf = b""
        self.next_id = 2
        self.handlers = {1: self._display_event}
        self.globals = {}           # interface -> (name, version)
        self.lock = threading.Lock()
        self.queue = []
        self.wake_r, self.wake_w = os.pipe()
        self.toplevels = {}         # ext handle id -> Toplevel
        self.by_cosmic = {}
        self.serial = 0
        self.idle_since = None      # monotonic time input went idle (None = busy right now)
        self.last_input = time.monotonic()
        self.resumes = 0            # idle -> busy flips so far
        self.cursor_buffer_px = None  # (x, y) of the mouse on the first output, in its buffer px, or None
        self.motions = 0            # mouse moves so far (counted like macOS counts input events, never read)
        self.shm_formats = set()
        self.alive = True

        reg = self._new(self._registry_event)
        self._send(1, WL_DISPLAY_GET_REGISTRY, struct.pack("<I", reg))
        self._roundtrip()
        self.registry = reg
        self._bind_all()
        self._roundtrip()
        self._roundtrip()  # toplevel handles announced in the first round get their cosmic info in the second
        threading.Thread(target=self._run, name="flippy-wayland", daemon=True).start()

    # ---- wire
    def _new(self, handler):
        oid = self.next_id
        self.next_id += 1
        self.handlers[oid] = handler
        return oid

    def _send(self, obj, op, payload=b"", fds=()):
        msg = struct.pack("<II", obj, ((8 + len(payload)) << 16) | op) + payload
        with self.lock:
            if fds:
                self.sock.sendmsg([msg], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))])
            else:
                self.sock.sendall(msg)

    def _read(self, timeout=None):
        r, _, _ = select.select([self.sock, self.wake_r], [], [], timeout)
        if self.wake_r in r:
            os.read(self.wake_r, 512)
        if self.sock not in r:
            return
        data, anc, _, _ = self.sock.recvmsg(65536, socket.CMSG_SPACE(16 * 4))
        for level, kind, fdata in anc:  # nothing we bind sends fds; close any so they don't leak
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                for fd in array.array("i", fdata[:len(fdata) - len(fdata) % 4]):
                    os.close(fd)
        if not data:
            self.alive = False
            raise WaylandError("compositor closed the connection")
        self.buf += data
        while len(self.buf) >= 8:
            obj, so = struct.unpack_from("<II", self.buf)
            size, op = so >> 16, so & 0xFFFF
            if len(self.buf) < size:
                break
            body, self.buf = self.buf[8:size], self.buf[size:]
            handler = self.handlers.get(obj)
            if handler:
                handler(op, _Reader(body))

    def _roundtrip(self, timeout=2.0):
        done = []
        cb = self._new(lambda op, r: done.append(1))
        self._send(1, WL_DISPLAY_SYNC, struct.pack("<I", cb))
        end = time.monotonic() + timeout
        while not done and time.monotonic() < end:
            self._read(max(end - time.monotonic(), 0))
        self.handlers.pop(cb, None)

    def _display_event(self, op, r):
        if op == 0:  # error
            obj, code, msg = r.u(), r.u(), r.s()
            print(f"flippy: wayland error on object {obj} ({code}): {msg}", flush=True)
        elif op == 1:  # delete_id
            self.handlers.pop(r.u(), None)

    def _registry_event(self, op, r):
        if op == 0:
            name, iface, version = r.u(), r.s(), r.u()
            if iface in WANT and iface not in self.globals:
                self.globals[iface] = (name, version)

    def _bind(self, iface, handler=None):
        if iface not in self.globals:
            return None
        name, version = self.globals[iface]
        version = min(version, WANT[iface])
        oid = self._new(handler or (lambda op, r: None))
        self._send(self.registry, WL_REGISTRY_BIND, struct.pack("<I", name) + _string(iface) + struct.pack("<II", version, oid))
        return oid

    # ---- setup
    def _bind_all(self):
        self.seat = self._bind("wl_seat")
        self.shm = self._bind("wl_shm", self._shm_event)
        self.output = self._bind("wl_output")  # the first one: single monitor, like the rest of Flippy
        self.cosmic_info = self._bind("zcosmic_toplevel_info_v1")  # v2+: events come per ext handle we ask about
        self.toplevel_list = self._bind("ext_foreign_toplevel_list_v1", self._list_event)
        self.capture = self._bind("ext_image_copy_capture_manager_v1")
        self.toplevel_sources = self._bind("ext_foreign_toplevel_image_capture_source_manager_v1")
        self.output_sources = self._bind("ext_output_image_capture_source_manager_v1")
        self.vk_manager = self._bind("zwp_virtual_keyboard_manager_v1")
        self.vk = None
        notifier = self._bind("ext_idle_notifier_v1")
        if notifier and self.seat:
            input_only = self.globals["ext_idle_notifier_v1"][1] >= 2  # v2: ignores idle inhibitors (video players)
            idle = self._new(self._idle_event)
            self._send(notifier, IDLE_GET_INPUT_NOTIFICATION if input_only else IDLE_GET_NOTIFICATION,
                       struct.pack("<III", idle, IDLE_MS, self.seat))
        if self.capture and self.output_sources and self.output and self.seat:
            self._watch_cursor()

    def _shm_event(self, op, r):
        if op == 0:
            self.shm_formats.add(r.u())

    def _idle_event(self, op, r):
        now = time.monotonic()
        if op == 0:  # idled: the last input was IDLE_MS ago
            self.idle_since = now - IDLE_MS / 1000
            self.last_input = self.idle_since
        elif op == 1:  # resumed
            self.idle_since = None
            self.last_input = now
            self.resumes += 1

    def idle_s(self):
        since = self.idle_since
        return 0.0 if since is None else time.monotonic() - since

    # ---- toplevels
    def _list_event(self, op, r):
        if op == 0:  # toplevel
            oid = r.u()
            tl = Toplevel(oid)
            self.serial += 1
            tl.serial = self.serial
            self.handlers[oid] = lambda op, rr, tl=tl: self._ext_handle_event(tl, op, rr)
            self.toplevels = {**self.toplevels, oid: tl}
            if self.cosmic_info:
                cid = self._new(lambda op, rr, tl=tl: self._cosmic_handle_event(tl, op, rr))
                tl.cosmic_id = cid
                self._send(self.cosmic_info, TOPLEVEL_INFO_GET_COSMIC_TOPLEVEL, struct.pack("<II", cid, oid))

    def _ext_handle_event(self, tl, op, r):
        if op == 0:  # closed
            self.toplevels = {k: v for k, v in self.toplevels.items() if k != tl.ext_id}
        elif op == 2:
            tl.title = r.s()
        elif op == 3:
            tl.app_id = r.s()

    def _cosmic_handle_event(self, tl, op, r):
        if op == 8:  # state
            states = struct.unpack(f"<{len(raw) // 4}I", raw) if (raw := r.a()) else ()
            tl.activated = COSMIC_STATE_ACTIVATED in states
        elif op == 9:  # geometry
            r.u()
            tl.geometry = (r.i(), r.i(), r.i(), r.i())

    def active(self):
        """The active (focused) toplevel, or None."""
        return next((t for t in self.toplevels.values() if t.activated), None)

    # ---- the mouse: a cursor capture session reports its position without capturing anything
    def _watch_cursor(self):
        pointer = self._new(lambda op, r: None)  # we have no surfaces on this connection, so it gets no events
        self._send(self.seat, WL_SEAT_GET_POINTER, struct.pack("<I", pointer))
        source = self._new(lambda op, r: None)
        self._send(self.output_sources, OUTPUT_SOURCE_CREATE, struct.pack("<II", source, self.output))
        self.cursor_session = self._new(self._cursor_event)
        self._send(self.capture, CAPTURE_CREATE_POINTER_CURSOR_SESSION, struct.pack("<III", self.cursor_session, source, pointer))

    def _cursor_event(self, op, r):
        if op == 1:  # leave
            self.cursor_buffer_px = None
        elif op == 2:  # position, in the source's buffer px
            self.cursor_buffer_px = (r.i(), r.i())
            self.motions += 1

    def cursor_logical(self, scale):
        p = self.cursor_buffer_px
        return None if p is None else (p[0] / scale, p[1] / scale)

    # ---- thumbnails of the active window
    def _run(self):
        while self.alive:
            with self.lock:
                jobs, self.queue = self.queue, []
            for job in jobs:
                job()
            try:
                self._read(1.0)
            except (OSError, WaylandError) as e:
                print(f"flippy: wayland watcher stopped: {e}", flush=True)
                self.alive = False

    def _call(self, fn):
        with self.lock:
            self.queue.append(fn)
        os.write(self.wake_w, b"x")

    def capture_window(self, toplevel, timeout=2.0):
        """(width, height, stride, PIL raw mode, bytes) of a toplevel's current contents, or None. Any thread
        but the Wayland one."""
        if not (self.capture and self.toplevel_sources and self.alive):
            return None
        return self._capture(self.toplevel_sources, TOPLEVEL_SOURCE_CREATE, toplevel.ext_id, timeout)

    def capture_screen(self, timeout=2.0):
        """The same for the whole (first) output, panel and Flippy's overlay included."""
        if not (self.capture and self.output_sources and self.output and self.alive):
            return None
        return self._capture(self.output_sources, OUTPUT_SOURCE_CREATE, self.output, timeout)

    def _capture(self, manager, op, target, timeout):
        out, done = {}, threading.Event()
        self._call(lambda: self._start_capture(manager, op, target, out, done))
        done.wait(timeout)
        return out.get("image")

    def _start_capture(self, manager, op, target, out, done):
        st = {"size": None, "formats": set()}
        source = self._new(lambda op, r: None)
        self._send(manager, op, struct.pack("<II", source, target))

        def session_event(op, r):
            if op == 0:
                st["size"] = (r.u(), r.u())
            elif op == 1:
                st["formats"].add(r.u())
            elif op == 4:  # done: constraints known, make the buffer and capture one frame
                self._capture_frame(session, source, st, out, done)
            elif op == 5:  # stopped (the window went away)
                cleanup()
        session = self._new(session_event)

        def cleanup():
            if st.get("closed"):
                return
            st["closed"] = True
            self._send(session, SESSION_DESTROY)
            self._send(source, SOURCE_DESTROY)
            done.set()
        st["cleanup"] = cleanup
        self._send(self.capture, CAPTURE_CREATE_SESSION, struct.pack("<III", session, source, 0))

    def _capture_frame(self, session, source, st, out, done):
        if st.get("frame") or not st["size"]:
            return
        fmt, mode = next(((f, m) for f, m in SHM_FORMATS if f in st["formats"]), (None, None))
        if fmt is None:
            st["cleanup"]()
            return
        w, h = st["size"]
        stride, size = w * 4, w * 4 * h
        fd = os.memfd_create("flippy-thumb", os.MFD_CLOEXEC)
        os.ftruncate(fd, size)
        mem = mmap.mmap(fd, size)
        pool = self._new(lambda op, r: None)
        self._send(self.shm, WL_SHM_CREATE_POOL, struct.pack("<Ii", pool, size), fds=[fd])
        os.close(fd)
        buffer = self._new(lambda op, r: None)
        self._send(pool, WL_SHM_POOL_CREATE_BUFFER, struct.pack("<IiiiiI", buffer, 0, w, h, stride, fmt))
        self._send(pool, WL_SHM_POOL_DESTROY)

        def frame_event(op, r):
            if op not in (3, 4):
                return
            if op == 3:  # ready
                out["image"] = (w, h, stride, mode, bytes(mem))
            self._send(frame, FRAME_DESTROY)
            self._send(buffer, WL_BUFFER_DESTROY)
            mem.close()
            st["cleanup"]()
        frame = self._new(frame_event)
        st["frame"] = frame
        self._send(session, SESSION_CREATE_FRAME, struct.pack("<I", frame))
        self._send(frame, FRAME_ATTACH_BUFFER, struct.pack("<I", buffer))
        self._send(frame, FRAME_DAMAGE_BUFFER, struct.pack("<iiii", 0, 0, w, h))
        self._send(frame, FRAME_CAPTURE)


    # ---- a virtual keyboard (scripted input). Each call brings its own keymap: keycode 9 + i types keysyms[i]
    def can_type(self):
        return bool(self.vk_manager and self.seat and self.alive)

    def set_keymap(self, keysyms):
        """keysyms: xkb keysym names (e.g. "U0041", "Return", "Control_L"). Key i is evdev code i + 1."""
        names = "".join(f"    <K{i}> = {i + 9};\n" for i in range(len(keysyms)))
        syms = "".join(f"    key <K{i}> {{ [ {k} ] }};\n" for i, k in enumerate(keysyms))
        text = ("xkb_keymap {\n"
                f"  xkb_keycodes \"flippy\" {{\n    minimum = 8;\n    maximum = {max(len(keysyms) + 9, 255)};\n{names}  }};\n"
                "  xkb_types \"flippy\" { include \"complete\" };\n"
                "  xkb_compatibility \"flippy\" { include \"complete\" };\n"
                f"  xkb_symbols \"flippy\" {{\n{syms}  }};\n"
                "};\n").encode() + b"\0"

        def go():
            if self.vk is None:
                self.vk = self._new(lambda op, r: None)
                self._send(self.vk_manager, VK_CREATE, struct.pack("<II", self.seat, self.vk))
            fd = os.memfd_create("flippy-keymap", os.MFD_CLOEXEC)
            os.write(fd, text)
            self._send(self.vk, VK_KEYMAP, struct.pack("<II", KEYMAP_XKB_V1, len(text)), fds=[fd])
            os.close(fd)
        self._call(go)

    def key(self, index, down):
        t = int(time.monotonic() * 1000) & 0xFFFFFFFF
        self._call(lambda: self._send(self.vk, VK_KEY, struct.pack("<III", t, index + 1, int(down))))

    def modifiers(self, mask):
        """mask of xkb's real modifiers: Shift 1, Control 4, Mod1 (Alt) 8, Mod4 (Super) 64."""
        self._call(lambda: self._send(self.vk, VK_MODIFIERS, struct.pack("<IIII", mask, 0, 0, 0)))


_conn = None
_conn_lock = threading.Lock()


def connection():
    """The shared Wayland watcher, connected on first use; None if this compositor can't do it."""
    global _conn
    with _conn_lock:
        if _conn is None or not _conn.alive:
            try:
                _conn = Wayland()
            except (OSError, WaylandError) as e:
                print(f"flippy: wayland watcher unavailable: {e}", flush=True)
                _conn = None
        return _conn
