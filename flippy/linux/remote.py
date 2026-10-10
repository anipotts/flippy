"""The real pointer on COSMIC, through the RemoteDesktop portal: what /act's clicks by position and `flippy-ask
click` use where macOS posts CGEvents.

The portal asks once (COSMIC's "allow remote desktop" dialog); its restore token is kept in
~/.config/flippy/remote-desktop-token (0600: it lets Flippy skip the dialog, so it's a credential, never logged),
and later sessions start without asking. A session also shares the screen (absolute pointer positions are in a
screen-cast stream's coordinates), which COSMIC shows in the panel while it's open, so a session only lives while
it's used: it closes after IDLE_CLOSE_S without input.

Everything runs on the caller's thread (a desktop task's worker), not GTK's: portal requests answer with a signal,
so each one waits on a private main context. The session belongs to the D-Bus connection that made it, and that
same connection sends the input.
"""
import os
import secrets
import threading

from gi.repository import Gio, GLib

from .. import settings

PORTAL = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
REMOTE = "org.freedesktop.portal.RemoteDesktop"
CAST = "org.freedesktop.portal.ScreenCast"
KEYBOARD, POINTER = 1, 2
MONITOR = 1
PERSIST_UNTIL_REVOKED = 2
BTN_LEFT = 0x110            # linux/input-event-codes.h
AXIS_VERTICAL, AXIS_HORIZONTAL = 0, 1
TOKEN_PATH = os.path.join(os.path.dirname(settings.PATH), "remote-desktop-token")
ASK_TIMEOUT_S = 120         # the first time, the user has to answer COSMIC's dialog
CALL_TIMEOUT_MS = 3000
IDLE_CLOSE_S = 20.0


class Unavailable(Exception):
    """No pointer: the portal isn't there, the user said no, or the session failed. str() says which, for Claude."""


class RemoteDesktop:
    def __init__(self):
        self.lock = threading.RLock()
        self.bus = None
        self.session = None
        self.stream = None          # (node id, (x, y) position, (w, h) size) of the monitor stream
        self.closer = None
        self.refused = False        # the user said no this run: don't show the dialog again until a restart

    # ---- portal plumbing
    def _call(self, iface, method, args, reply="(o)"):
        return self.bus.call_sync(PORTAL, PATH, iface, method, args, GLib.VariantType(reply) if reply else None,
                                  Gio.DBusCallFlags.NONE, CALL_TIMEOUT_MS, None)

    def _request(self, iface, method, signature, values, options, timeout_s=CALL_TIMEOUT_MS / 1000):
        """Call a portal method (its arguments: signature and values, then options) that answers with a Request's
        Response signal: (code, results)."""
        token = "flippy_" + secrets.token_hex(6)
        sender = self.bus.get_unique_name()[1:].replace(".", "_")
        handle = f"{PATH}/request/{sender}/{token}"
        ctx = GLib.MainContext.new()
        ctx.push_thread_default()
        answer = []
        try:
            sub = self.bus.signal_subscribe(PORTAL, "org.freedesktop.portal.Request", "Response", handle, None,
                                            Gio.DBusSignalFlags.NO_MATCH_RULE,
                                            lambda *a: answer.append(a[5].unpack()))
            try:
                options = {**options, "handle_token": GLib.Variant("s", token)}
                self._call(iface, method, GLib.Variant(f"({signature}a{{sv}})", (*values, options)))
                timed_out = []
                source = GLib.timeout_source_new(int(timeout_s * 1000))
                source.set_callback(lambda *a: timed_out.append(1) or False)
                source.attach(ctx)
                while not answer and not timed_out:
                    ctx.iteration(True)
                source.destroy()
            finally:
                self.bus.signal_unsubscribe(sub)
        finally:
            ctx.pop_thread_default()
        if not answer:
            raise Unavailable("COSMIC's remote desktop didn't answer.")
        return answer[0]

    # ---- the session
    def open(self):
        """Start a session if there isn't one. Raises Unavailable."""
        with self.lock:
            self._keep_open()
            if self.session:
                return
            if self.refused:
                raise Unavailable("The user didn't allow Flippy to use the pointer (COSMIC's remote desktop dialog).")
            try:
                self.bus = self.bus or Gio.bus_get_sync(Gio.BusType.SESSION, None)
                version = self.bus.call_sync(PORTAL, PATH, "org.freedesktop.DBus.Properties", "Get",
                                             GLib.Variant("(ss)", (REMOTE, "version")), GLib.VariantType("(v)"),
                                             Gio.DBusCallFlags.NONE, CALL_TIMEOUT_MS, None)
            except GLib.Error:
                raise Unavailable("Clicking by position needs COSMIC's remote desktop support (COSMIC Epoch 1.7 or "
                                  "newer), which this computer doesn't have.") from None
            persist = version.unpack()[0] >= 2
            try:
                self._start(persist)
            except GLib.Error:
                self._close()
                raise Unavailable("COSMIC's remote desktop session failed to start.") from None
            except Unavailable:
                self._close()
                raise

    def _start(self, persist):
        code, res = self._request(REMOTE, "CreateSession", "", (),
                                  {"session_handle_token": GLib.Variant("s", "flippy_" + secrets.token_hex(6))})
        if code != 0:
            raise Unavailable("COSMIC's remote desktop session failed to start.")
        self.session = res["session_handle"]
        devices = {"types": GLib.Variant("u", KEYBOARD | POINTER)}
        if persist:
            devices["persist_mode"] = GLib.Variant("u", PERSIST_UNTIL_REVOKED)
            token = _read_token()
            if token:
                devices["restore_token"] = GLib.Variant("s", token)
        code, _ = self._request(REMOTE, "SelectDevices", "o", (self.session,), devices)
        if code != 0:
            raise Unavailable("COSMIC's remote desktop session failed to start.")
        # absolute pointer positions need a stream to be relative to: the monitor
        code, _ = self._request(CAST, "SelectSources", "o", (self.session,),
                                {"types": GLib.Variant("u", MONITOR), "multiple": GLib.Variant("b", False)})
        if code != 0:
            raise Unavailable("COSMIC's remote desktop session failed to start.")
        code, res = self._request(REMOTE, "Start", "os", (self.session, ""), {}, timeout_s=ASK_TIMEOUT_S)
        if code == 1:
            self.refused = True
            raise Unavailable("The user didn't allow Flippy to use the pointer (COSMIC's remote desktop dialog).")
        if code != 0 or not int(res.get("devices", 0)) & POINTER:
            raise Unavailable("COSMIC's remote desktop didn't give Flippy the pointer.")
        if res.get("restore_token"):
            _write_token(res["restore_token"])
        streams = res.get("streams") or []
        if not streams:
            raise Unavailable("COSMIC's remote desktop gave no screen to point in.")
        node, props = streams[0]
        self.stream = (node, tuple(props.get("position", (0, 0))), tuple(props.get("size", (0, 0))))

    def _keep_open(self):
        if self.closer:
            self.closer.cancel()
        self.closer = threading.Timer(IDLE_CLOSE_S, self.close)
        self.closer.daemon = True
        self.closer.start()

    def close(self):
        with self.lock:
            self._close()

    def _close(self):
        if self.session and self.bus:
            try:
                self.bus.call_sync(PORTAL, self.session, "org.freedesktop.portal.Session", "Close", None, None,
                                   Gio.DBusCallFlags.NONE, CALL_TIMEOUT_MS, None)
            except GLib.Error:
                pass
        self.session = self.stream = None

    # ---- input (screen points: logical px of the single monitor)
    def _notify(self, method, signature, *values):
        try:
            self._call(REMOTE, method, GLib.Variant(f"(oa{{sv}}{signature})", (self.session, {}, *values)), None)
        except GLib.Error:
            self._close()
            raise Unavailable("COSMIC's remote desktop session ended.") from None

    def move(self, x, y, screen_size):
        """Pointer to (x, y) on the screen, mapped into the monitor stream's coordinates."""
        node, (sx, sy), (sw, sh) = self.stream
        kx = sw / screen_size[0] if sw else 1
        ky = sh / screen_size[1] if sh else 1
        self._notify("NotifyPointerMotionAbsolute", "udd", node, float(sx + x * kx), float(sy + y * ky))

    def button(self, down, button=BTN_LEFT):
        self._notify("NotifyPointerButton", "iu", button, 1 if down else 0)

    def scroll(self, direction, lines):
        axis = AXIS_VERTICAL if direction in ("up", "down") else AXIS_HORIZONTAL
        self._notify("NotifyPointerAxisDiscrete", "ui", axis, lines if direction in ("down", "right") else -lines)


def _read_token():
    try:
        with open(TOKEN_PATH) as f:
            return f.read().strip()
    except OSError:
        return None


def _write_token(token):
    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(str(token))
    os.chmod(TOKEN_PATH, 0o600)


_shared = None


def shared():
    global _shared
    if _shared is None:
        _shared = RemoteDesktop()
    return _shared
