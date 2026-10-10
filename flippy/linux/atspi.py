"""Background desktop tasks on COSMIC: one app's window, worked through AT-SPI, Linux's accessibility layer.

The Linux side of flippy/mac/ax.py, with its function names and behavior. /act works on a target app (the one in
front when the task started, or one it switched to with use_app), whether or not that app is in front:

  see:  that app's window, captured on its own through Wayland (wl.capture_window: other windows on top don't
        matter), plus a numbered list of its controls from AT-SPI
  act:  press / set a control's text / focus it / pick a menu item / insert text at its cursor, all through
        AT-SPI, which apps take in the background

Wayland has no way to send keys or clicks to one app, so those borrow the window for a moment while the user is
idle (flippy/linux/borrow.py); the few keys AT-SPI can do itself (return, delete, select all, copy, cut, paste in a
text control) don't.

Where things are: AT-SPI gives positions in WINDOW coordinates (SCREEN ones aren't real on Wayland). GTK3 counts
them from the surface, shadow margin included; GTK4 from the visible window. Wayland's capture and the window's
geometry are the visible window, and the window's top-level children cover exactly that, so their corner is the
offset between the two (_origin).

Which app: Wayland says which window is in front (its app id and title); AT-SPI lists apps by process. match_app
pairs them by flatpak id, the window's title among the app's windows, or the app's executable.

AT-SPI calls are D-Bus calls to the target app, so they run on the task's worker thread, never GTK's.
"""
import base64
import io
import os
import re
import threading
import time

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, Gio, GLib  # noqa: E402

from ..actions import WAYLAND, ActionError, RetryableActionError  # noqa: E402
from . import sensors, wl  # noqa: E402

MAX_ELEMENTS = 150      # controls listed per look
MAX_DEPTH = 40          # GTK trees nest deeper than AppKit's
MAX_VISITED = 4000      # nodes walked per look, so a huge table can't stall the task
VALUE_CHARS = 80        # a control's current value, as shown to Claude
SEND_LONG_EDGE = 1600
LAUNCH_WAIT_S = 10.0
CALL_TIMEOUT_MS = 2000  # one AT-SPI call; a hung app can't hold the task for D-Bus's default 25 s
MENU_ITEMS = 25         # items listed per menu
NO_PID = 1 << 22        # handles above any pid (pid_max is at most 2^22), for windows whose app isn't on AT-SPI

# controls worth listing, by AT-SPI role name: things you can press, type into, pick, or read as a label
ROLES = {
    "push button": "button", "button": "button", "toggle button": "toggle button", "check box": "checkbox",
    "radio button": "radio", "switch": "switch", "text": "text area", "entry": "text field",
    "password text": "password field", "combo box": "combo box", "spin button": "stepper", "slider": "slider",
    "link": "link", "page tab": "tab", "list item": "row", "table row": "row", "tree item": "row",
    "table cell": "cell", "menu item": "menu item", "check menu item": "menu item", "radio menu item": "menu item",
    "menu": "menu", "color chooser": "color well", "date editor": "date field", "label": "text",
    "static": "text", "heading": "heading", "image": "image", "icon": "image", "document web": "web area",
}
TEXT_ROLES = ("text", "entry", "password text")
CHECKABLE = ("check box", "toggle button", "radio button", "switch", "check menu item", "radio menu item")
PRESSABLE = ("push button", "button", "toggle button", "check box", "radio button", "switch", "link", "page tab",
             "menu item", "check menu item", "radio menu item", "combo box", "list item", "tree item")
# action names that press a control, most direct first (GTK: click; Qt: Press, Toggle; Firefox: jump, activate...)
PRESS_ACTIONS = ("click", "press", "activate", "jump", "toggle", "open", "select", "check", "uncheck", "switch",
                 "expand or contract", "expand", "collapse")
WINDOW_ROLES = ("frame", "window", "dialog", "alert", "file chooser")
MENU_BUTTON_NAMES = ("menu", "main menu", "primary menu", "application menu", "open menu", "more options",
                     "more", "hamburger menu")

S = Atspi.StateType
COORDS = Atspi.CoordType.WINDOW

_lock = threading.Lock()
_ready = False
_handles = {}           # synthetic handle -> app id (see NO_PID)
_origins = {}           # (handle, window id) -> (dx, dy): visible window coords + this = AT-SPI WINDOW coords
_focused = {}           # handle -> the control Flippy last focused there (a background window may report none)


def _init():
    global _ready
    with _lock:
        if not _ready:
            Atspi.init()
            Atspi.set_timeout(CALL_TIMEOUT_MS, 15000)
            _ready = True


def enable():
    """Ask apps to expose their controls: org.a11y.Status.IsEnabled, the standard switch (GTK and Qt read it; apps
    that were already running when it flipped may only expose theirs after a restart). Never ScreenReaderEnabled:
    that changes how every app behaves."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    props = ("org.a11y.Bus", "/org/a11y/bus", "org.freedesktop.DBus.Properties")
    on = bus.call_sync(*props, "Get", GLib.Variant("(ss)", ("org.a11y.Status", "IsEnabled")),
                       GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, CALL_TIMEOUT_MS, None).unpack()[0]
    if not on:
        bus.call_sync(*props, "Set", GLib.Variant("(ssv)", ("org.a11y.Status", "IsEnabled", GLib.Variant("b", True))),
                      None, Gio.DBusCallFlags.NONE, CALL_TIMEOUT_MS, None)


def preflight():
    try:
        enable()
        _init()
        Atspi.get_desktop(0).get_child_count()
    except Exception:
        raise ActionError("Flippy can't reach Linux's accessibility service (AT-SPI), so it can't see apps' "
                          "controls. Install at-spi2-core, log out and back in, then try again.") from None
    conn = wl.connection()
    if conn is None or not conn.capture or not conn.toplevel_sources:
        raise ActionError("This desktop doesn't let Flippy see app windows (it needs COSMIC's window capture). "
                          "Desktop tasks need COSMIC.")


def _gone(err=None):
    raise RetryableActionError("That control is gone or the app is busy. Look again, then try.") from err


def _short(value):
    if value is None:
        return ""
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= VALUE_CHARS else text[:VALUE_CHARS - 1] + "…"


def _children(el):
    try:
        n = el.get_child_count()
    except GLib.Error:
        return
    for i in range(n):
        try:
            child = el.get_child_at_index(i)
        except GLib.Error:
            continue
        if child is not None:
            yield child


def _has(states, *names):
    return all(states.contains(getattr(S, n)) for n in names)


def _extents(el):
    """(x, y, w, h) in WINDOW coordinates, or None for something not laid out (GTK reports those at -2^31)."""
    try:
        e = Atspi.Component.get_extents(el, COORDS)
    except (GLib.Error, TypeError):
        return None
    if e.width <= 0 or e.height <= 0 or e.x < -100000 or e.y < -100000:
        return None
    return e.x, e.y, e.width, e.height


def _actions(el):
    """[(index, name)] of the actions that press it, most direct first."""
    try:
        names = [(Atspi.Action.get_action_name(el, i) or "").lower() for i in range(Atspi.Action.get_n_actions(el))]
    except (GLib.Error, TypeError, AttributeError):
        return []
    return sorted(((i, n) for i, n in enumerate(names) if n in PRESS_ACTIONS), key=lambda a: PRESS_ACTIONS.index(a[1]))


def _text(el, limit=VALUE_CHARS + 1):
    try:
        n = Atspi.Text.get_character_count(el)
        return Atspi.Text.get_text(el, 0, min(n, limit)) if n else ""
    except (GLib.Error, TypeError, AttributeError):
        return ""


def _editable(el, states=None):
    try:
        states = states or el.get_state_set()
        return "EditableText" in el.get_interfaces() and states.contains(S.EDITABLE)
    except GLib.Error:
        return False


def _title(t):
    """A menu title as matched: no case, and "Save As…" == "Save As..." == "Save As"."""
    return re.sub(r"(…|\.\.\.)$", "", str(t or "").strip().lower()).strip()


# ---- which app

def _proc(pid):
    """What /proc says about a process: its command name, executable and flatpak app id."""
    info = {"comm": "", "exe": "", "flatpak": ""}
    try:
        with open(f"/proc/{pid}/comm") as f:
            info["comm"] = f.read().strip()
    except OSError:
        pass
    try:
        info["exe"] = os.path.basename(os.readlink(f"/proc/{pid}/exe"))
    except OSError:
        pass
    try:
        with open(f"/proc/{pid}/root/.flatpak-info") as f:
            info["flatpak"] = next((ln[5:].strip() for ln in f if ln.startswith("name=")), "")
    except OSError:
        pass
    return info


def match_app(app_id, title, candidates, exec_names=()):
    """Which AT-SPI app (its pid) shows the Wayland window app_id / title, or None.
    candidates: [{"pid", "name", "frames": [window titles], "comm", "exe", "flatpak"}]; exec_names: the
    executable and window class the app's .desktop file names. The flatpak id is certain, a window title nearly
    so, a process name only a hint (several apps can share one)."""
    app_id = app_id or ""
    want = {n.lower() for n in (app_id, app_id.rsplit(".", 1)[-1], *exec_names) if n}
    best, best_score = None, 0
    for c in candidates:
        score = 0
        if c.get("flatpak") and c["flatpak"].lower() == app_id.lower():
            score += 4
        if title and title in c.get("frames", ()):
            score += 2
        if {(c.get(k) or "").lower() for k in ("comm", "exe", "name")} & want:
            score += 1
        if score > best_score:
            best, best_score = c["pid"], score
    return best


def _exec_names(app_id):
    for cand in (app_id, app_id.lower()):
        try:
            info = Gio.DesktopAppInfo.new(cand + ".desktop")
        except TypeError:
            info = None
        if info:
            exe = os.path.basename(info.get_executable() or "")
            return [n for n in (exe, info.get_startup_wm_class()) if n and n != "flatpak"]
    return []


def _apps():
    """[(accessible, name, pid)] of the apps on the accessibility bus, Flippy left out."""
    _init()
    out = []
    for app in _children(Atspi.get_desktop(0)):
        try:
            pid = app.get_process_id()
            if pid != os.getpid():
                out.append((app, app.get_name() or "", pid))
        except GLib.Error:
            continue
    return out


def _find(app_id, title):
    """(accessible, pid) of the AT-SPI app behind that window, or (None, None)."""
    apps = _apps()
    candidates = []
    for app, name, pid in apps:
        frames = []
        for i, frame in enumerate(_children(app)):
            if i >= 20:
                break
            try:
                frames.append(frame.get_name() or "")
            except GLib.Error:
                pass
        candidates.append({"pid": pid, "name": name, "frames": frames, **_proc(pid)})
    pid = match_app(app_id, title, candidates, _exec_names(app_id))
    return next((a for a, _, p in apps if p == pid), None), pid


def _handle(app_id, pid):
    """The task's handle on an app: its pid, or a stable stand-in when it isn't on the accessibility bus."""
    if pid:
        return pid
    for h, a in _handles.items():
        if a == app_id:
            return h
    h = NO_PID + len(_handles) + 1
    _handles[h] = app_id
    return h


def _toplevel(conn, app_id, title=None):
    """The app's window: the one with the focus, else the one it last had or opened most recently (a dialog it
    just opened in the background counts)."""
    tls = [t for t in conn.toplevels.values() if t.app_id == app_id]
    if title:
        tls = [t for t in tls if t.title == title] or tls
    if not tls:
        return None
    return next((t for t in tls if t.activated), None) or max(tls, key=lambda t: (max(t.active_at, t.seen_at), t.serial))


def front_app():
    """(app id, name, handle) of the app in front, if it isn't Flippy. On COSMIC the question box is a window that
    takes the focus (flippy/linux/ui.py InputBox), so /act typed there means the window that had it before."""
    conn = wl.connection()
    tl = before_flippy(conn.toplevels.values() if conn else ())
    if tl is None:
        raise ActionError("Put the app you want Flippy to work in in front, then start /act again.")
    _, pid = _find(tl.app_id, tl.title)
    return tl.app_id, sensors.app_name(tl.app_id), _handle(tl.app_id, pid)


def before_flippy(toplevels):
    """The window in front, or, when that's one of Flippy's own, the one that had the focus last before it."""
    tls = [t for t in toplevels if t.app_id]
    active = next((t for t in tls if t.activated), None)
    if active is not None and active.app_id != wl.SELF_APP_ID:
        return active
    others = [t for t in tls if t.app_id != wl.SELF_APP_ID and t.active_at]
    return max(others, key=lambda t: t.active_at) if others else None


def find_app(name):
    """A running app with a window, by name (case-insensitive): its display name or app id. (id, name, handle)."""
    want = name.strip().lower()
    conn = wl.connection()
    if conn is None:
        return None
    for tl in sorted(conn.toplevels.values(), key=lambda t: max(t.active_at, t.seen_at), reverse=True):
        if not tl.app_id or tl.app_id == wl.SELF_APP_ID:
            continue
        if want in (sensors.app_name(tl.app_id).lower(), tl.app_id.lower(), tl.app_id.rsplit(".", 1)[-1].lower()):
            _, pid = _find(tl.app_id, tl.title)
            return tl.app_id, sensors.app_name(tl.app_id), _handle(tl.app_id, pid)
    return None


def _desktop_entry(name):
    """The installed app called that: by its name, generic name ("Text Editor") or id; else the only one whose
    name contains it."""
    want = name.strip().lower()
    apps = [a for a in Gio.AppInfo.get_all() if a.should_show()]

    def names(a):
        out = [a.get_display_name(), a.get_name(), (a.get_id() or "").removesuffix(".desktop")]
        if isinstance(a, Gio.DesktopAppInfo):
            out.append(a.get_generic_name())
        return [n.lower() for n in out if n]
    exact = [a for a in apps if want in names(a)]
    if exact:
        return exact[0]
    partial = [a for a in apps if want in (a.get_display_name() or "").lower()]
    return partial[0] if len(partial) == 1 else None


def open_app(name, cancel):
    """Find the app by name, or open it. (id, name, handle). A new window takes the focus on COSMIC (no way to open
    one behind), so the window the user was in gets it back as soon as the app's appears."""
    found = find_app(name)
    if found:
        return found
    info = _desktop_entry(name)
    if info is None:
        raise RetryableActionError(f"There's no app called {name!r} on this computer. Check the name and try again.")
    conn = wl.connection()
    before, known = conn.active(), set(conn.toplevels)
    ids = {n.lower() for n in ((info.get_id() or "").removesuffix(".desktop"),
                               *(_exec_names((info.get_id() or "").removesuffix(".desktop")))) if n}
    try:
        info.launch([], None)
    except GLib.Error:
        raise RetryableActionError(f"{name} couldn't be opened. Try use_app again.") from None
    deadline = time.monotonic() + LAUNCH_WAIT_S
    while time.monotonic() < deadline and not cancel.is_set():
        new = [t for k, t in conn.toplevels.items() if k not in known and t.app_id and t.app_id != wl.SELF_APP_ID]
        tl = next((t for t in new if t.app_id.lower() in ids or t.app_id.rsplit(".", 1)[-1].lower() in ids),
                  new[0] if len(new) == 1 else None)
        if tl is not None:
            _give_back(conn, tl, before)
            acc = pid = None
            while acc is None and time.monotonic() < deadline and not cancel.is_set():  # AT-SPI lags the window
                acc, pid = _find(tl.app_id, tl.title)
                if acc is None:
                    time.sleep(0.25)
            return tl.app_id, sensors.app_name(tl.app_id), _handle(tl.app_id, pid)
        time.sleep(0.25)
    raise RetryableActionError(f"{name} didn't open in time. Try use_app again.")


def _give_back(conn, tl, before, wait_s=1.0):
    """The new window took the focus: hand it back to the window the user was in."""
    if before is None or before.ext_id not in conn.toplevels or before is tl:
        return
    end = time.monotonic() + wait_s
    while not tl.activated and time.monotonic() < end:
        time.sleep(0.05)
    if tl.activated:
        conn.activate(before)


# ---- its window

def _frame(app, title):
    """The app's AT-SPI window for that Wayland window: same title, else the active one, else the first shown."""
    frames = []
    for child in _children(app):
        try:
            if child.get_role_name() in WINDOW_ROLES:
                frames.append((child, child.get_name() or "", child.get_state_set()))
        except GLib.Error:
            continue
    return (next((f for f, name, _ in frames if title and name == title), None)
            or next((f for f, _, st in frames if st.contains(S.ACTIVE)), None)
            or next((f for f, _, st in frames if st.contains(S.SHOWING)), None)
            or (frames[0][0] if frames else None))


def origin(boxes, width, height):
    """Where the visible window (width x height) starts in AT-SPI's WINDOW coordinates, from the boxes of the
    window's top-level children: their union is the visible window. What's left over is a server-side title bar
    above and a thin border around, which AT-SPI doesn't count."""
    boxes = [b for b in boxes if b]
    if not boxes:
        return 0, 0
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    w = max(b[0] + b[2] for b in boxes) - x0
    h = max(b[1] + b[3] for b in boxes) - y0
    return x0 - max(0, width - w) / 2, y0 - max(0, height - h)


def _origin(frame, geometry):
    boxes = []
    for child in _children(frame):
        try:
            if child.get_state_set().contains(S.SHOWING):
                boxes.append(_extents(child))
        except GLib.Error:
            continue
    return origin(boxes, geometry[2], geometry[3])


def _capture(conn, tl):
    """That window alone, as a PIL image (other windows on top don't show), or None."""
    from PIL import Image
    img = conn.capture_window(tl)
    if img is None:
        return None
    w, h, stride, mode, data = img
    return Image.frombuffer("RGBA" if mode in ("RGBA", "BGRA") else "RGBX", (w, h), data, "raw", mode, stride, 1)


def look(app_id, name, handle):
    """What Claude sees: (jpeg b64 or None, image size, target, elements, description).
    elements: {id: (accessible, role, label, actions, can_set)}; ids are only good until the next look.
    A window that's minimized, can't be captured, or whose app shows AT-SPI nothing isn't a dead end: what can
    be listed still is, and media and app actions work without a window."""
    _init()
    conn = wl.connection()
    if conn is None:
        raise ActionError("Flippy lost its connection to the desktop. Restart Flippy.")
    tl = _toplevel(conn, app_id)
    app, pid = _find(app_id, tl.title if tl else None)
    if tl is None and app is None:
        print(f"flippy: act: {name} looks gone: had handle {handle} app id {app_id!r}", flush=True)
        raise ActionError(f"{name} quit. Start a new /act request.")
    handle = _handle(app_id, pid)
    frame = _frame(app, tl.title if tl else None) if app is not None else None
    title = _short(tl.title if tl else frame.get_name() if frame is not None else "")
    geometry = tl.geometry if tl is not None and tl.geometry else None
    image = _capture(conn, tl) if tl is not None and geometry and not tl.minimized else None
    if image is not None:
        k = min(1.0, SEND_LONG_EDGE / max(image.size))
        if k < 1:
            image = image.resize((round(image.width * k), round(image.height * k)))
        scale = image.width / geometry[2]   # window px -> image px
    else:
        scale = 1.0
    geometry = geometry or (0, 0, 0, 0)
    dx, dy = _origin(frame, geometry) if frame is not None and geometry[2] else (0, 0)
    window = tl.ext_id if tl is not None else None
    _origins[(handle, window)] = (dx, dy)

    elements, lines, menu_buttons = {}, [], []
    if frame is not None:
        _walk(frame, elements, lines, menu_buttons, lambda box: (round((box[0] - dx) * scale),
                                                                 round((box[1] - dy) * scale),
                                                                 round(box[2] * scale), round(box[3] * scale)))
    if image is not None:
        state = (f"window {title!r}, screenshot {image.width}x{image.height} px "
                 f"(control positions are in these pixels)")
    elif tl is None:
        state = "no window open. Use media or app_action for playback, or a menu that opens a window"
    elif tl.minimized:
        state = f"window {title!r} is minimized: no screenshot, but its controls below can still be used"
    else:
        state = f"window {title!r} can't be captured: no screenshot, controls listed below"
    if app is None:
        state += (". This app doesn't show its controls to Linux's accessibility layer, so none are listed: "
                  "work by position in the screenshot (click, scroll, drag), keys, and app_action")
    jpeg = None
    if image is not None:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=80)
        jpeg = base64.b64encode(buf.getvalue()).decode()
    text = (f"App: {name} — {state}.\n"
            f"Menus (items marked (off) are greyed out right now):\n{_menus(frame, menu_buttons)}\n"
            f"Controls ({len(elements)}{'+' if len(elements) >= MAX_ELEMENTS else ''}):\n"
            + ("\n".join(lines) if lines else "(none)"))
    target = (app_id, handle, window, geometry, WAYLAND)
    return jpeg, image.size if image is not None else (0, 0), target, elements, text


def describe(n, kind, label, value, where, ops, off=False):
    """One control's line in the look, in flippy/mac/ax.py's format."""
    return (f"[{n}] {kind} {label!r}" + (" (off)" if off else "") + (f" = {value!r}" if value else "")
            + f" ({where[0]},{where[1]} {where[2]}x{where[3]})" + (f" [{', '.join(ops)}]" if ops else ""))


def _walk(frame, elements, lines, menu_buttons, to_image):
    visited = 0

    def visit(el, depth, owner):
        nonlocal visited
        visited += 1
        if depth > MAX_DEPTH or visited > MAX_VISITED or len(elements) >= MAX_ELEMENTS:
            return
        try:
            states = el.get_state_set()
            if depth and not states.contains(S.SHOWING):
                return  # hidden, and so is everything inside it (a closed popover, another tab's page)
            role = el.get_role_name()
            kind = ROLES.get(role)
            if role == "menu bar":
                return  # listed under Menus
            if kind:
                label = _short(el.get_name() or el.get_description())
                value = ""
                if role in TEXT_ROLES or (role in ("label", "static", "heading") and not label):
                    value = "" if role == "password text" else _short(_text(el))
                elif role in CHECKABLE:
                    value = "on" if states.contains(S.CHECKED) or states.contains(S.PRESSED) else "off"
                elif "Value" in el.get_interfaces():
                    try:
                        value = _short(f"{Atspi.Value.get_current_value(el):g}")
                    except (GLib.Error, TypeError):
                        pass
                if role in ("label", "static", "heading") and not label:
                    label, value = value, ""
                if role in TEXT_ROLES and states.contains(S.SINGLE_LINE):
                    kind = "text field"
                acts = _actions(el)
                can_set = _editable(el, states)
                box = _extents(el)
                inside = role in ("label", "static", "image", "icon") and label and label == owner
                if (acts or can_set or label or value) and box and not inside:
                    n = len(elements) + 1
                    ops = (["press"] if acts else []) + (["set_text", "focus"] if can_set else [])
                    off = not states.contains(S.SENSITIVE) and not states.contains(S.ENABLED)
                    lines.append(describe(n, kind, label, value, to_image(box), ops, off))
                    elements[n] = (el, role, label or kind, acts, can_set)
                    if acts and (states.contains(S.HAS_POPUP) or _title(label) in MENU_BUTTON_NAMES):
                        menu_buttons.append(label)
                    owner = label or owner
        except GLib.Error:
            return
        for child in _children(el):
            visit(child, depth + 1, owner)
    visit(frame, 0, None)


def _menu_bars(frame):
    """The window's menu bars (GTK3, Qt, LibreOffice and Firefox have one; GTK4 apps a menu button instead)."""
    found = []

    def visit(el, depth):
        if depth > 8 or len(found) > 1:
            return
        for child in _children(el):
            try:
                role = child.get_role_name()
            except GLib.Error:
                continue
            if role == "menu bar":
                found.append(child)
            elif role not in TEXT_ROLES and role != "menu":
                visit(child, depth + 1)
    if frame is not None:
        visit(frame, 0)
    return found


def _items(menu):
    """A menu's items, skipping separators and the containers some toolkits put between."""
    out = []
    for child in _children(menu):
        try:
            role = child.get_role_name()
        except GLib.Error:
            continue
        if role in ("menu item", "check menu item", "radio menu item", "menu", "tearoff menu item"):
            out.append(child)
        elif role in ("panel", "filler", "list", "section", "menu bar"):
            out.extend(_items(child))
    return out


def _menus(frame, menu_buttons=()):
    """The window's menus and their items, one line per menu ("File: New, Open…, Recent >, Close (off)"), and
    the menu buttons apps without a menu bar have."""
    out = []
    for bar in _menu_bars(frame):
        for top in _items(bar):
            try:
                title = _short(top.get_name())
            except GLib.Error:
                continue
            items = []
            for it in _items(top):
                try:
                    t = (it.get_name() or "").strip()
                    if not t:
                        continue
                    st = it.get_state_set()
                    items.append(t + (" (off)" if not st.contains(S.SENSITIVE) and not st.contains(S.ENABLED) else "")
                                 + (" >" if it.get_role_name() == "menu" else ""))
                except GLib.Error:
                    continue
            if title:
                out.append(f"  {title}: " + ", ".join(items[:MENU_ITEMS]) + (", ..." if len(items) > MENU_ITEMS else ""))
    if menu_buttons:
        out.append("  Menu buttons (their items show after pressing; menu presses the button and the item for you, "
                   f'e.g. ["{menu_buttons[0]}", "<item>"]): ' + ", ".join(repr(b) for b in dict.fromkeys(menu_buttons)))
    return "\n".join(out) or "  (none)"


# ---- acting (on the task's worker thread)

def app_and_frame(target):
    """(app accessible, its window) for a look's target, or (None, None) when its app isn't on AT-SPI."""
    app_id, handle, window = target[:3]
    if handle >= NO_PID:
        return None, None
    _init()
    app = next((a for a, _, pid in _apps() if pid == handle), None)
    if app is None:
        return None, None
    conn = wl.connection()
    tl = conn.toplevels.get(window) if conn and window is not None else None
    return app, _frame(app, tl.title if tl else None)


def press(el, acts):
    for index, _ in acts:
        try:
            if Atspi.Action.do_action(el, index):
                return
        except GLib.Error as err:
            _gone(err)
    raise RetryableActionError("That control can't be pressed. Look again and pick another, or use the menus.")


def set_text(el, text):
    if not _editable(el):
        raise RetryableActionError("That control's text can't be set directly. focus it and use type instead.")
    try:
        ok = Atspi.EditableText.set_text_contents(el, text)
        took = Atspi.Text.get_text(el, 0, -1) == text
    except GLib.Error as err:
        _gone(err)
    if not ok or not took:
        raise RetryableActionError("The app refused that text. focus the control and use type instead.")


def focus(el, handle):
    try:
        ok = Atspi.Component.grab_focus(el)
    except GLib.Error as err:
        _gone(err)
    if not ok:
        raise RetryableActionError("That control can't take focus. Pick a text field or text area.")
    _focused[handle] = el


def _typing_target(frame, handle):
    """The control typing goes into: the focused editable one, else the one Flippy focused, else the window's
    only editable text control. None when there's none (typing then needs real keys)."""
    found, editable = [], []

    def visit(el, depth):
        if depth > MAX_DEPTH or len(editable) > 20:
            return
        try:
            st = el.get_state_set()
            if depth and not st.contains(S.SHOWING):
                return
            if _editable(el, st):
                editable.append(el)
                if st.contains(S.FOCUSED):
                    found.append(el)
        except GLib.Error:
            return
        for child in _children(el):
            visit(child, depth + 1)
    if frame is not None:
        visit(frame, 0)
    if found:
        return found[0]
    mine = _focused.get(handle)
    if mine is not None and any(mine == e for e in editable):
        return mine
    return editable[0] if len(editable) == 1 else None


def insert_text(frame, handle, text):
    """Insert at the typing target's cursor, in the background. False when there's no target or the app refused,
    so the caller types it for real instead."""
    el = _typing_target(frame, handle)
    if el is None:
        return False
    try:
        offset = Atspi.Text.get_caret_offset(el)
        count = Atspi.Text.get_character_count(el)
        offset = count if offset < 0 or offset > count else offset
        # the length is in bytes: GTK drops text cut in the middle of a character
        if not Atspi.EditableText.insert_text(el, offset, text, len(text.encode())):
            return False
        if Atspi.Text.get_character_count(el) != count + len(text):
            return False
        Atspi.Text.set_caret_offset(el, offset + len(text))  # entries leave the cursor before what went in
    except GLib.Error:
        return False
    return True


def background_key(frame, handle, combo):
    """The keys AT-SPI can do on the typing target without the window in front. True if done."""
    if combo not in BACKGROUND_KEYS:
        return False
    el = _typing_target(frame, handle)
    if el is None:
        return False
    try:
        st = el.get_state_set()
        caret = Atspi.Text.get_caret_offset(el)
        count = Atspi.Text.get_character_count(el)
        sel = Atspi.Text.get_selection(el, 0) if Atspi.Text.get_n_selections(el) else None
        start, end = (sel.start_offset, sel.end_offset) if sel and sel.end_offset > sel.start_offset else (caret, caret)
        if combo == "return":
            if st.contains(S.MULTI_LINE):
                return insert_text(frame, handle, "\n")
            index = next((i for i, n in _all_actions(el) if n == "activate"), None)
            return index is not None and bool(Atspi.Action.do_action(el, index))
        if combo == "delete":
            if end == start:
                start = max(0, caret - 1)
            return end > start and bool(Atspi.EditableText.delete_text(el, start, end))
        if combo == "ctrl+a":
            return bool(Atspi.Text.set_selection(el, 0, 0, count) if sel else Atspi.Text.add_selection(el, 0, count))
        if combo in ("ctrl+c", "ctrl+x"):
            if end == start:
                return False
            fn = Atspi.EditableText.copy_text if combo == "ctrl+c" else Atspi.EditableText.cut_text
            return bool(fn(el, start, end))
        if combo == "ctrl+v":
            return bool(Atspi.EditableText.paste_text(el, caret if caret >= 0 else count))
    except GLib.Error:
        return False
    return False


BACKGROUND_KEYS = ("return", "delete", "ctrl+a", "ctrl+c", "ctrl+x", "ctrl+v")


def _all_actions(el):
    try:
        return [(i, (Atspi.Action.get_action_name(el, i) or "").lower()) for i in range(Atspi.Action.get_n_actions(el))]
    except (GLib.Error, TypeError, AttributeError):
        return []


def _shown_items(frame):
    """Menu and popover items on screen now: [(accessible, title, enabled)]."""
    out = []

    def visit(el, depth):
        if depth > MAX_DEPTH or len(out) > 200:
            return
        try:
            st = el.get_state_set()
            if depth and not st.contains(S.SHOWING):
                return
            role = el.get_role_name()
            if role in PRESSABLE and role not in ("list item", "tree item", "page tab") and _actions(el):
                out.append((el, (el.get_name() or "").strip(),
                            st.contains(S.SENSITIVE) or st.contains(S.ENABLED)))
        except GLib.Error:
            return
        for child in _children(el):
            visit(child, depth + 1)
    if frame is not None:
        visit(frame, 0)
    return out


def menu(frame, path):
    """Pick a menu item by its titles without opening the menu on screen: ["File", "Save As…"] from the menu bar,
    or ["Menu", "Preferences"] from a menu button (it's pressed, then the item)."""
    bars = _menu_bars(frame)
    tops = [it for bar in bars for it in _items(bar)]
    if tops and any(_title(_name(t)) == _title(path[0]) for t in tops):
        node, items = None, tops
        for title in path:
            node = next((it for it in items if _title(_name(it)) == _title(title)), None)
            if node is None:
                names = [_name(it) for it in items if _name(it)]
                raise RetryableActionError(f"No menu item {title!r} there. Choices: {', '.join(names[:40])}")
            items = _items(node)
        _press_item(node, path)
        return
    _menu_button(frame, path, tops)


def _name(el):
    try:
        return (el.get_name() or "").strip()
    except GLib.Error:
        return ""


def _press_item(node, path):
    try:
        st = node.get_state_set()
    except GLib.Error as err:
        _gone(err)
    if not st.contains(S.SENSITIVE) and not st.contains(S.ENABLED):
        raise RetryableActionError(f"{' > '.join(path)} is greyed out right now.")
    acts = _actions(node)
    if not acts:
        raise RetryableActionError(f"Couldn't pick {' > '.join(path)}.")
    try:
        if not Atspi.Action.do_action(node, acts[0][0]):
            raise RetryableActionError(f"Couldn't pick {' > '.join(path)}.")
    except GLib.Error as err:
        _gone(err)


def _menu_button(frame, path, tops):
    """A menu button's popover: press the button, then each title as it shows up. Closes it again on a miss."""
    shown = _shown_items(frame)
    button = next((el for el, title, _ in shown if _title(title) == _title(path[0])), None)
    if button is None:
        bar = ", ".join(_name(t) for t in tops if _name(t))
        buttons = ", ".join(dict.fromkeys(t for _, t, _ in shown if _title(t) in MENU_BUTTON_NAMES))
        raise RetryableActionError(f"No menu or menu button {path[0]!r}. "
                                   + (f"Menus: {bar}. " if bar else "")
                                   + (f"Menu buttons: {buttons}." if buttons else "Look for the app's menu button."))
    if len(path) == 1:
        _press_item(button, path)
        return
    before = {_title(t) for _, t, _ in shown}
    _press_item(button, path[:1])
    for i, title in enumerate(path[1:], start=1):
        item = None
        end = time.monotonic() + 1.5  # the popover maps a moment after the press
        while item is None and time.monotonic() < end:
            time.sleep(0.1)
            item = next(((el, ok) for el, t, ok in _shown_items(frame) if _title(t) == _title(title)), None)
        if item is None:
            choices = [t for _, t, _ in _shown_items(frame) if t and _title(t) not in before]
            _close(button)
            raise RetryableActionError(f"No item {title!r} in {' > '.join(path[:i])}."
                                       + (f" Choices: {', '.join(choices[:40])}" if choices else ""))
        if not item[1]:
            _close(button)
            raise RetryableActionError(f"{' > '.join(path[:i + 1])} is greyed out right now.")
        _press_item(item[0], path[:i + 1])


def _close(button):
    """Close a popover Flippy opened: its toggle button is still pressed."""
    try:
        st = button.get_state_set()
        if st.contains(S.CHECKED) or st.contains(S.PRESSED):
            acts = _actions(button)
            if acts:
                Atspi.Action.do_action(button, acts[0][0])
    except GLib.Error:
        pass


def to_window(target, x, y):
    """Screen point (logical px) -> the app's AT-SPI WINDOW coordinates."""
    dx, dy = _origins.get((target[1], target[2]), (0, 0))
    fx, fy = target[3][:2]
    return x - fx + dx, y - fy + dy


def press_at(frame, x, y):
    """If a real control sits at that window point, press it through AT-SPI, in the background. True if it did."""
    if frame is None:
        return False
    try:
        el = frame
        for _ in range(MAX_DEPTH):  # get_accessible_at_point gives the child under the point: go down to the deepest
            child = Atspi.Component.get_accessible_at_point(el, int(x), int(y), COORDS)
            if child is None or child == el:
                break
            el = child
        for _ in range(4):  # the label or icon inside a button: its button
            if el is None or el == frame:
                return False
            if el.get_role_name() in PRESSABLE:
                acts = _actions(el)
                return bool(acts) and bool(Atspi.Action.do_action(el, acts[0][0]))
            el = el.get_parent()
    except (GLib.Error, TypeError):
        return False
    return False
