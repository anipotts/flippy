"""Help mode's signals on COSMIC (see flippy/watch.py), and tutorial clicks. All cheap, all local.

Everything comes from flippy/linux/wl.py's private Wayland connection:
- frontmost app: the activated toplevel's app_id (its .desktop Name for display)
- idle seconds: ext-idle-notify (input only)
- input event count: mouse moves (counted, never read) plus a few per idle -> busy flip,
  since Wayland doesn't let an ordinary app count key presses
- screen thumbnail: a 64x40 grayscale capture of the active window only, so the
  panel's clock and Flippy's own overlay never count as change
- the frontmost app's windows: toplevel ids and geometry
"""
import threading
import time

from gi.repository import Gio, GLib

from ..watch import Sample
from . import wl

THUMB_W, THUMB_H = 64, 40
RESUME_EVENTS = 5           # an idle -> busy flip counts as this many events (it stands for typing we can't count)

# tutorials: a "click" is the mouse at a spot, then the screen reacting
CLICK_POLL_S = 0.15         # mouse position
CLICK_THUMB_S = 0.4         # screen thumbnail
CLICK_TRAIL_S = 2.0         # where the mouse was this long before the reaction is where they clicked
CLICK_THUMB_W, CLICK_THUMB_H = 128, 72
CLICK_PIXEL = 0.08          # a thumbnail pixel this much brighter/darker changed...
CLICK_AREA = 0.01           # ...and this fraction of them changing = something reacted (a menu, a panel, a page)

_names = {}


def app_name(app_id):
    """The app's display name from its .desktop file, else its id's last part. The file is usually named after
    the app id; when it isn't (gedit's window says "gedit", its file is org.gnome.gedit.desktop), it's the one
    whose window class or executable is the app id."""
    if app_id not in _names:
        name = None
        for cand in (app_id, app_id.lower()):
            try:
                info = Gio.DesktopAppInfo.new(cand + ".desktop")
            except TypeError:
                info = None
            if info:
                name = info.get_name()
                break
        if name is None:
            want = app_id.lower()
            name = next((a.get_name() for a in Gio.AppInfo.get_all() if isinstance(a, Gio.DesktopAppInfo)
                         and want in ((a.get_startup_wm_class() or "").lower(),
                                      (a.get_executable() or "").rsplit("/", 1)[-1].lower())), None)
        _names[app_id] = name or app_id.rsplit(".", 1)[-1].replace("-", " ").title()
    return _names[app_id]


def frontmost():
    """(app id, name) of the active window, or (None, None). Flippy's own windows count as None."""
    conn = wl.connection()
    tl = conn.active() if conn else None
    if tl is None or not tl.app_id or tl.app_id == wl.SELF_APP_ID:
        return None, None
    return tl.app_id, app_name(tl.app_id)


def _gray(img, w, h):
    """A capture shrunk to w x h grayscale values in 0-1."""
    from PIL import Image
    iw, ih, stride, mode, data = img
    im = Image.frombuffer("RGBA" if mode in ("RGBA", "BGRA") else "RGBX", (iw, ih), data, "raw", mode, stride, 1)
    return [b / 255 for b in im.convert("L").resize((w, h), Image.BOX).tobytes()]


def thumbnail(conn, toplevel, w=THUMB_W, h=THUMB_H):
    img = conn.capture_window(toplevel)
    return _gray(img, w, h) if img else None


def sample(want_thumb=True):
    conn = wl.connection()
    tl = conn.active() if conn else None
    if tl is None or not tl.app_id or tl.app_id == wl.SELF_APP_ID:
        return Sample(time.monotonic(), None)
    same_app = [t for t in conn.toplevels.values() if t.app_id == tl.app_id and t.geometry]
    return Sample(
        t=time.monotonic(), app=tl.app_id, app_name=app_name(tl.app_id),
        idle_s=conn.idle_s(),
        events=conn.motions + RESUME_EVENTS * conn.resumes,
        thumb=thumbnail(conn, tl) if want_thumb else None,
        windows=sorted(((t.ext_id, t.geometry) for t in same_app), key=lambda w: -w[1][2] * w[1][3]) or None,
    )


def input_idle_s():
    conn = wl.connection()
    return conn.idle_s() if conn else 1e9


class ClickWatcher:
    """Calls on_click(x, y) (logical px, main thread) when they seem to have clicked at (x, y).

    Wayland never tells an ordinary app about clicks in other windows, so this
    infers them: the screen reacted (a big enough change outside Flippy's own
    card and pointer, another window became active, a new window opened, or the
    active one's title changed) and the mouse was at (x, y) just before. Every
    recent mouse position is reported; the controller keeps one near the step's
    target, if any, so a reaction somewhere else doesn't count.

    ink(): [(x, y, w, h)] in logical px that Flippy itself paints (left out of the comparison).
    """

    def __init__(self, on_click, scale, screen_size, ink):
        self.on_click = on_click
        self.scale = scale
        self.screen = screen_size
        self.ink = ink
        self.stop_ev = threading.Event()
        threading.Thread(target=self._run, name="flippy-clicks", daemon=True).start()

    def stop(self):
        self.stop_ev.set()

    @staticmethod
    def _state(conn):
        tl = conn.active()
        return (tl.ext_id if tl else None, tl.title if tl else None, frozenset(conn.toplevels)), tl

    def _thumb(self, conn):
        img = conn.capture_screen()
        return _gray(img, CLICK_THUMB_W, CLICK_THUMB_H) if img else None

    def _changed(self, a, b):
        """Fraction of thumbnail pixels that changed, outside what Flippy paints."""
        sw, sh = self.screen
        kx, ky = CLICK_THUMB_W / sw, CLICK_THUMB_H / sh
        skip = set()
        for x, y, w, h in self.ink():
            for ty in range(max(int(y * ky), 0), min(int((y + h) * ky) + 1, CLICK_THUMB_H)):
                for tx in range(max(int(x * kx), 0), min(int((x + w) * kx) + 1, CLICK_THUMB_W)):
                    skip.add(ty * CLICK_THUMB_W + tx)
        n = len(a) - len(skip)
        changed = sum(1 for i, (p, q) in enumerate(zip(a, b)) if abs(p - q) > CLICK_PIXEL and i not in skip)
        return changed / n if n > 0 else 0.0

    def _run(self):
        conn = wl.connection()
        if conn is None:
            return
        trail = []                  # [(t, x, y)]
        state, _ = self._state(conn)
        thumb = self._thumb(conn)
        next_thumb = time.monotonic() + CLICK_THUMB_S
        while not self.stop_ev.wait(CLICK_POLL_S):
            now = time.monotonic()
            pos = conn.cursor_logical(self.scale)
            if pos and (not trail or trail[-1][1:] != pos):
                trail.append((now, *pos))
            trail = [p for p in trail if now - p[0] <= CLICK_TRAIL_S] or trail[-1:]
            new_state, tl = self._state(conn)
            reacted = new_state[0] != state[0] or new_state[1] != state[1] or bool(new_state[2] - state[2])
            if tl is not None and tl.app_id == wl.SELF_APP_ID:
                reacted = False  # Flippy's own windows (settings, the question box)
            state = new_state
            if now >= next_thumb or reacted:
                next_thumb = now + CLICK_THUMB_S
                new_thumb = self._thumb(conn)
                if not reacted and thumb and new_thumb and len(thumb) == len(new_thumb):
                    reacted = self._changed(thumb, new_thumb) >= CLICK_AREA
                thumb = new_thumb
            if reacted and trail and not self.stop_ev.is_set():
                spots = [(x, y) for _, x, y in reversed(trail)]
                GLib.idle_add(lambda s=spots: [self.on_click(x, y) for x, y in s] and False)
                trail = trail[-1:]
