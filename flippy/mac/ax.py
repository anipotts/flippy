"""Background desktop tasks on macOS: one app's window, worked through the Accessibility API.

/act no longer drives the real pointer and keyboard. It works on a target app (the one in front when the task
started, or one it switched to with use_app), whether or not that app is in front:

  see:  that app's window, captured on its own (CGWindowListCreateImage with its window id, so other windows
        on top don't matter), plus a numbered list of its controls from the Accessibility API
  act:  press / set a control's text / focus it / pick a menu item, all through the Accessibility API, and
        typing and shortcuts sent to that app's process (CGEventPostToPid), not to whatever is in front

Your pointer never moves and the app you're in keeps the keyboard. Clicking, scrolling and dragging by
coordinates come later (pointer-free events to the window, then borrowing the mouse while you're idle).

AX calls are IPC to the target app, so they run on the task's worker thread, not the Cocoa run loop.
"""
import base64
import io
import os
import subprocess
import time

import AppKit
import ApplicationServices as AX
import Quartz

from ..actions import ActionError, RetryableActionError
from . import hotkeys

MAX_ELEMENTS = 150      # controls listed per look
MAX_DEPTH = 30
MAX_VISITED = 4000      # AX nodes walked per look, so a huge table can't stall the task
VALUE_CHARS = 80        # a control's current value, as shown to Claude
SEND_LONG_EDGE = 1600
LAUNCH_WAIT_S = 10.0

# controls worth listing: things you can press, type into, pick, or read as a label
ROLES = {
    "AXButton": "button", "AXMenuButton": "menu button", "AXPopUpButton": "pop-up", "AXCheckBox": "checkbox",
    "AXRadioButton": "radio", "AXTextField": "text field", "AXTextArea": "text area", "AXSearchField": "search field",
    "AXComboBox": "combo box", "AXSlider": "slider", "AXIncrementor": "stepper", "AXLink": "link", "AXTab": "tab",
    "AXRadioGroup": "tab group", "AXDisclosureTriangle": "disclosure", "AXRow": "row", "AXCell": "cell",
    "AXOutlineRow": "row", "AXMenuItem": "menu item", "AXColorWell": "color well", "AXDateField": "date field",
    "AXSegmentedControl": "segmented", "AXSwitch": "switch", "AXStaticText": "text", "AXHeading": "heading",
    "AXImage": "image", "AXWebArea": "web area",
}
PRESS_ACTIONS = ("AXPress", "AXConfirm", "AXPick", "AXOpen")
ERR_GONE = (-25202, -25204)   # kAXErrorInvalidUIElement, kAXErrorCannotComplete (app busy or element gone)


def trusted():
    return bool(AX.AXIsProcessTrusted())


def _attr(el, name):
    err, value = AX.AXUIElementCopyAttributeValue(el, name, None)
    return value if err == 0 else None


def _actions(el):
    err, names = AX.AXUIElementCopyActionNames(el, None)
    return list(names or []) if err == 0 else []


def _settable(el, name="AXValue"):
    err, ok = AX.AXUIElementIsAttributeSettable(el, name, None)
    return err == 0 and bool(ok)


def _point(value, kind):
    """AXValueRef (position or size) -> (a, b)."""
    if value is None:
        return None
    ok, out = AX.AXValueGetValue(value, kind, None)
    if not ok:
        return None
    return (out.x, out.y) if kind == AX.kAXValueCGPointType else (out.width, out.height)


def _frame(el):
    pos = _point(_attr(el, "AXPosition"), AX.kAXValueCGPointType)
    size = _point(_attr(el, "AXSize"), AX.kAXValueCGSizeType)
    return (pos[0], pos[1], size[0], size[1]) if pos and size else None


def _short(value):
    if value is None:
        return ""
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= VALUE_CHARS else text[:VALUE_CHARS - 1] + "…"


# ---- which app

def running_app(pid):
    app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    return app if app is not None and not app.isTerminated() else None


def front_app():
    """(bundle id, name, pid) of the app in front, if it isn't Flippy."""
    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None or app.processIdentifier() == os.getpid():
        raise ActionError("Put the app you want Flippy to work in in front, then start /act again.")
    return str(app.bundleIdentifier() or ""), str(app.localizedName()), app.processIdentifier()


def find_app(name):
    """A running app by name (case-insensitive), or None."""
    want = name.strip().lower()
    for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
        if app.activationPolicy() == AppKit.NSApplicationActivationPolicyRegular and \
                str(app.localizedName() or "").lower() == want and app.processIdentifier() != os.getpid():
            return str(app.bundleIdentifier() or ""), str(app.localizedName()), app.processIdentifier()
    return None


def open_app(name, cancel):
    """Find the app by name, or open it without bringing it to the front (`open -g`). (bundle, name, pid)."""
    found = find_app(name)
    if found:
        return found
    r = subprocess.run(["/usr/bin/open", "-g", "-a", name], capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        raise RetryableActionError(f"There's no app called {name!r} on this Mac. Check the name and try again.")
    deadline = time.monotonic() + LAUNCH_WAIT_S
    while time.monotonic() < deadline and not cancel.is_set():
        found = find_app(name)
        if found and _window(found[2]) is not None:
            return found
        time.sleep(0.25)
    if found:
        return found
    raise RetryableActionError(f"{name} didn't open in time. Try use_app again.")


# ---- its window

def _window(pid):
    """The app's focused (or main, or first) window as an AX element, or None."""
    app = AX.AXUIElementCreateApplication(pid)
    for name in ("AXFocusedWindow", "AXMainWindow"):
        win = _attr(app, name)
        if win is not None:
            return win
    wins = _attr(app, "AXWindows") or []
    return wins[0] if wins else None


def _window_id(pid, frame, title):
    """The CG window number matching that AX window (same owner, same bounds; title breaks ties)."""
    info = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID) or []
    best = None
    for win in info:
        if win.get("kCGWindowOwnerPID") != pid or win.get("kCGWindowLayer", 0) != 0:
            continue
        b = win.get("kCGWindowBounds") or {}
        if frame and all(abs(a - c) < 2 for a, c in zip((b.get("X"), b.get("Y"), b.get("Width"), b.get("Height")), frame)):
            if best is None or (title and win.get("kCGWindowName") == title):
                best = int(win["kCGWindowNumber"])
    return best


def _capture(window_id):
    """That window alone, as a PIL image (other windows on top don't show), or None."""
    from PIL import Image
    img = Quartz.CGWindowListCreateImage(Quartz.CGRectNull, Quartz.kCGWindowListOptionIncludingWindow, window_id,
                                         Quartz.kCGWindowImageBoundsIgnoreFraming | Quartz.kCGWindowImageNominalResolution)
    if img is None or Quartz.CGImageGetWidth(img) <= 1:
        return None
    w, h = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
    data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img))
    return Image.frombuffer("RGBA", (w, h), bytes(data), "raw", "BGRA", Quartz.CGImageGetBytesPerRow(img), 1)


def look(bundle, name, pid):
    """What Claude sees: (jpeg b64, image size, target, elements, description).
    elements: {id: (AX element, role, label, actions)}; ids are only good until the next look."""
    if running_app(pid) is None:
        raise ActionError(f"{name} quit. Start a new /act request.")
    win = _window(pid)
    if win is None:
        raise RetryableActionError(f"{name} has no open window. Open one (menu File > New, or a key), then look again.")
    frame = _frame(win)
    title = _short(_attr(win, "AXTitle"))
    wid = _window_id(pid, frame, title)
    image = _capture(wid) if wid else None
    if image is None or frame is None:
        raise RetryableActionError(f"Couldn't see {name}'s window (minimized or on another space?). Look again.")
    k = min(1.0, SEND_LONG_EDGE / max(image.size))
    if k < 1:
        image = image.resize((round(image.width * k), round(image.height * k)))
    sx, sy = image.width / frame[2], image.height / frame[3]   # screen points -> image pixels

    elements, lines, visited = {}, [], 0

    def visit(el, depth):
        nonlocal visited
        visited += 1
        if depth > MAX_DEPTH or visited > MAX_VISITED or len(elements) >= MAX_ELEMENTS:
            return
        role = _attr(el, "AXRole")
        kind = ROLES.get(role)
        if kind:
            label = _short(_attr(el, "AXTitle") or _attr(el, "AXDescription") or _attr(el, "AXHelp")
                           or _attr(el, "AXPlaceholderValue"))
            value = _short(_attr(el, "AXValue")) if role not in ("AXStaticText",) or not label else ""
            if role == "AXStaticText" and not label:
                label, value = value, ""
            acts = [a for a in _actions(el) if a in PRESS_ACTIONS]
            can_set = _settable(el)
            box = _frame(el)
            if (acts or can_set or label or value) and box and box[2] > 0 and box[3] > 0:
                n = len(elements) + 1
                ops = (["press"] if acts else []) + (["set_text", "focus"] if can_set else [])
                where = f"({round((box[0] - frame[0]) * sx)},{round((box[1] - frame[1]) * sy)} " \
                        f"{round(box[2] * sx)}x{round(box[3] * sy)})"
                lines.append(f"[{n}] {kind} {label!r}" + (f" = {value!r}" if value else "") + f" {where}"
                             + (f" [{', '.join(ops)}]" if ops else ""))
                elements[n] = (el, role, label or kind, acts, can_set)
        for child in _attr(el, "AXChildren") or []:
            visit(child, depth + 1)
    visit(win, 0)

    menus = [_short(_attr(item, "AXTitle")) for item in
             (_attr(_attr(AX.AXUIElementCreateApplication(pid), "AXMenuBar"), "AXChildren") or [])][1:]  # skip Apple
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=80)
    text = (f"App: {name} — window {title!r}, screenshot {image.width}x{image.height} px "
            f"(element positions are in these pixels).\n"
            f"Menus: {', '.join(m for m in menus if m)}\n"
            f"Controls ({len(elements)}{'+' if len(elements) >= MAX_ELEMENTS else ''}):\n" + "\n".join(lines))
    target = (bundle, pid, wid, frame, 0)
    return base64.b64encode(buf.getvalue()).decode(), image.size, target, elements, text


# ---- acting

def _check(cancel):
    if cancel.is_set():
        raise ActionError("Task canceled.")


def _gone(err):
    if err in ERR_GONE:
        raise RetryableActionError("That control is gone or the app is busy. Look again, then try.")


def press(el, acts):
    for action in acts or PRESS_ACTIONS[:1]:
        err = AX.AXUIElementPerformAction(el, action)
        if err == 0:
            return
        _gone(err)
    raise RetryableActionError("That control can't be pressed. Look again and pick another, or use the menus.")


def set_text(el, text):
    if not _settable(el):
        raise RetryableActionError("That control's text can't be set directly. focus it and use type instead.")
    err = AX.AXUIElementSetAttributeValue(el, "AXValue", text)
    _gone(err)
    if err != 0:
        raise RetryableActionError("The app refused that text. focus the control and use type instead.")


def focus(el, pid):
    win = _window(pid)
    if win is not None:
        AX.AXUIElementPerformAction(win, "AXRaise")  # front within its app; the app itself stays where it is
    err = AX.AXUIElementSetAttributeValue(el, "AXFocused", True)
    _gone(err)
    if err != 0:
        raise RetryableActionError("That control can't take focus. Pick a text field or text area.")


def menu(pid, path):
    """Pick a menu item by its titles, e.g. ["File", "New Note"], without opening the menu on screen."""
    bar = _attr(AX.AXUIElementCreateApplication(pid), "AXMenuBar")
    node = bar
    for i, title in enumerate(path):
        items = []
        for child in _attr(node, "AXChildren") or []:
            # a menu bar item / submenu item holds its AXMenu as its only child
            if _attr(child, "AXRole") == "AXMenu":
                items.extend(_attr(child, "AXChildren") or [])
            else:
                items.append(child)
        match = next((it for it in items if str(_attr(it, "AXTitle") or "").strip().lower() == title.strip().lower()),
                     None)
        if match is None:
            names = [str(_attr(it, "AXTitle")) for it in items if _attr(it, "AXTitle")]
            raise RetryableActionError(f"No menu item {title!r} there. Choices: {', '.join(names[:40])}")
        node = match
    if _attr(node, "AXEnabled") is False:
        raise RetryableActionError(f"{' > '.join(path)} is greyed out right now.")
    err = AX.AXUIElementPerformAction(node, "AXPress")
    _gone(err)
    if err != 0:
        raise RetryableActionError(f"Couldn't pick {' > '.join(path)}.")


def _post(pid, code, down, flags=0, text=None):
    ev = Quartz.CGEventCreateKeyboardEvent(None, code, down)
    Quartz.CGEventSetFlags(ev, flags)
    if text is not None:
        Quartz.CGEventKeyboardSetUnicodeString(ev, len(text.encode("utf-16-le")) // 2, text)
    Quartz.CGEventPostToPid(pid, ev)


def type_text(pid, text, cancel):
    """Typing that goes to that app's focused control, wherever you are. Inserts at its cursor through the
    Accessibility API when the control allows it (works in the background); otherwise key events to the app."""
    focused = _attr(AX.AXUIElementCreateApplication(pid), "AXFocusedUIElement")
    if focused is not None and _settable(focused, "AXSelectedText"):
        err = AX.AXUIElementSetAttributeValue(focused, "AXSelectedText", text)
        if err == 0:
            return
        _gone(err)
    if not Quartz.CGPreflightPostEventAccess():
        raise ActionError("Allow Flippy in macOS Accessibility settings, then restart it.")
    for ch in text:
        _check(cancel)
        code = hotkeys.KEYS.get("space" if ch == " " else ch.lower(), 0)  # the text itself rides on the event
        flags = Quartz.kCGEventFlagMaskShift if ch.isupper() else 0
        _post(pid, code, True, flags, ch)
        _post(pid, code, False, flags, ch)
        time.sleep(0.012)


def key(pid, combo, flags_by_mod):
    if not Quartz.CGPreflightPostEventAccess():
        raise ActionError("Allow Flippy in macOS Accessibility settings, then restart it.")
    parts = [p.strip().lower() for p in combo.split("+")]
    code = hotkeys.KEYS.get(parts[-1])
    if code is None:
        raise RetryableActionError(f"Unknown key {parts[-1]!r}.")
    flags = 0
    for m in parts[:-1]:
        flags |= flags_by_mod[m]
    _post(pid, code, True, flags)
    _post(pid, code, False, flags)
