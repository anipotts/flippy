"""Scripted keystrokes on COSMIC (flippy-ask type/key/tap, behind automation.clicks), through a virtual keyboard.

Like wtype: every call uploads a small keymap with just the keysyms it needs, so
any character can be typed whatever the layout. Moving or clicking the mouse
isn't possible: cosmic-comp has no virtual pointer protocol and its portal no
RemoteDesktop (docs/linux-port.md).
"""
import random
import threading
import time

from . import wl

NO_KEYBOARD = "this compositor doesn't offer a virtual keyboard (zwp_virtual_keyboard_manager_v1)"
MODS = {"shift": 1, "ctrl": 4, "control": 4, "alt": 8, "option": 8, "opt": 8, "super": 64, "cmd": 64, "logo": 64}
MOD_KEYS = {1: "Shift_L", 4: "Control_L", 8: "Alt_L", 64: "Super_L"}
NAMED = {"escape": "Escape", "esc": "Escape", "return": "Return", "enter": "Return", "space": "space", "tab": "Tab",
         "delete": "BackSpace", "backspace": "BackSpace", "forwarddelete": "Delete", "left": "Left", "right": "Right",
         "up": "Up", "down": "Down", "home": "Home", "end": "End", "pageup": "Prior", "pagedown": "Next"}
_lock = threading.Lock()   # one gesture at a time: they share the keyboard's keymap


def keysym(ch):
    """An xkb keysym name for one character."""
    return {"\n": "Return", "\t": "Tab", " ": "space"}.get(ch) or f"U{ord(ch):04X}"


def _conn():
    conn = wl.connection()
    return conn if conn and conn.can_type() else None


def _press(conn, index, hold=0.02):
    conn.key(index, True)
    time.sleep(hold)
    conn.key(index, False)


def type_text(text, on_key=None):
    conn = _conn()
    if conn is None:
        return NO_KEYBOARD
    syms = sorted({keysym(ch) for ch in text})

    def run():
        with _lock:
            conn.set_keymap(syms)
            time.sleep(0.05)
            for ch in text:
                _press(conn, syms.index(keysym(ch)))
                if on_key:
                    on_key(ch)
                time.sleep(random.uniform(0.045, 0.11) + (0.12 if ch in " ,." else 0))
    threading.Thread(target=run, daemon=True).start()
    return "ok"


def key(combo):
    """A shortcut like ctrl+shift+t, escape or return, pressed for real."""
    conn = _conn()
    if conn is None:
        return NO_KEYBOARD
    parts = [p.strip().lower() for p in combo.split("+")]
    mask = 0
    for m in parts[:-1]:
        if m not in MODS:
            return f"unknown modifier {m!r}"
        mask |= MODS[m]
    last = parts[-1]
    sym = NAMED.get(last) or (keysym(last) if len(last) == 1 else
                              last.upper() if last[:1] == "f" and last[1:].isdigit() else None)
    if sym is None:
        return f"unknown key {last!r}"
    with _lock:
        conn.set_keymap([sym])
        time.sleep(0.05)
        conn.modifiers(mask)
        _press(conn, 0, 0.03)
        conn.modifiers(0)
    return "ok"


def tap(mod, times):
    """Tap a modifier on its own (double-tap shortcuts)."""
    conn = _conn()
    if conn is None:
        return NO_KEYBOARD
    mask = MODS.get(mod)
    if mask is None:
        return f"unknown modifier {mod!r}"

    def run():
        with _lock:
            conn.set_keymap([MOD_KEYS[mask]])
            time.sleep(0.05)
            for _ in range(times):
                conn.key(0, True)
                conn.modifiers(mask)
                time.sleep(0.07)
                conn.key(0, False)
                conn.modifiers(0)
                time.sleep(0.12)
    threading.Thread(target=run, daemon=True).start()
    return "ok"
