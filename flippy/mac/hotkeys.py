"""Global hotkeys through Carbon's RegisterEventHotKey (via ctypes).

Needs no Accessibility permission, and the keystroke is consumed instead of
also reaching the app in front. Carbon events are delivered by the Cocoa run
loop, so callbacks run on the main thread.
"""
import ctypes
from ctypes import POINTER, Structure, byref, c_uint32, c_void_p, c_int32

_carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")

MODS = {"cmd": 1 << 8, "shift": 1 << 9, "option": 1 << 11, "opt": 1 << 11, "alt": 1 << 11,
        "ctrl": 1 << 12, "control": 1 << 12}
KEYS = {  # ANSI virtual key codes
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12,
    "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
    "9": 25, "7": 26, "8": 28, "0": 29, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40,
    "n": 45, "m": 46, ",": 43, "/": 44, ".": 47, "space": 49, "return": 36, "tab": 48, "escape": 53,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100,
}
SYMBOLS = {"cmd": "⌘", "shift": "⇧", "option": "⌥", "opt": "⌥", "alt": "⌥", "ctrl": "⌃", "control": "⌃"}


def _fourcc(s):
    return int.from_bytes(s.encode(), "big")


class EventTypeSpec(Structure):
    _fields_ = [("eventClass", c_uint32), ("eventKind", c_uint32)]


class EventHotKeyID(Structure):
    _fields_ = [("signature", c_uint32), ("id", c_uint32)]


_HANDLER = ctypes.CFUNCTYPE(c_int32, c_void_p, c_void_p, c_void_p)
_carbon.GetApplicationEventTarget.restype = c_void_p
_carbon.InstallEventHandler.argtypes = [c_void_p, _HANDLER, c_uint32, POINTER(EventTypeSpec), c_void_p, POINTER(c_void_p)]
_carbon.RegisterEventHotKey.argtypes = [c_uint32, c_uint32, EventHotKeyID, c_void_p, c_uint32, POINTER(c_void_p)]
_carbon.UnregisterEventHotKey.argtypes = [c_void_p]
_carbon.GetEventParameter.argtypes = [c_void_p, c_uint32, c_uint32, c_void_p, c_uint32, c_void_p, c_void_p]

_SIG = _fourcc("flpy")
_callbacks = {}   # hotkey id -> fn
_refs = {}        # hotkey id -> EventHotKeyRef
_handler = None   # keep the ctypes callback alive


def parse(combo):
    """'cmd+shift+space' -> (keycode, carbon modifiers). Raises ValueError."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts or parts[-1] not in KEYS:
        raise ValueError(f"unknown key in {combo!r}")
    mods = 0
    for p in parts[:-1]:
        if p not in MODS:
            raise ValueError(f"unknown modifier {p!r} in {combo!r}")
        mods |= MODS[p]
    return KEYS[parts[-1]], mods


def pretty(combo):
    """'cmd+shift+space' -> '⇧⌘Space' (macOS menu order: ⌃⌥⇧⌘)."""
    parts = [p.strip().lower() for p in combo.split("+")]
    order = "⌃⌥⇧⌘"
    mods = sorted({SYMBOLS.get(p, "") for p in parts[:-1]}, key=lambda s: order.find(s))
    key = parts[-1]
    return "".join(mods) + (key.capitalize() if len(key) > 1 else key.upper())


def _install():
    global _handler
    if _handler:
        return

    def on_event(_call, event, _data):
        hk = EventHotKeyID()
        _carbon.GetEventParameter(event, _fourcc("----"), _fourcc("hkid"), None, ctypes.sizeof(hk), None, byref(hk))
        fn = _callbacks.get(hk.id)
        if fn:
            fn()
        return 0
    _handler = _HANDLER(on_event)
    spec = EventTypeSpec(_fourcc("keyb"), 5)  # kEventClassKeyboard, kEventHotKeyPressed
    ref = c_void_p()
    _carbon.InstallEventHandler(_carbon.GetApplicationEventTarget(), _handler, 1, byref(spec), None, byref(ref))


def register(hid, combo, fn):
    """Bind combo to fn under id hid (replacing what hid had). Returns an error string or None."""
    _install()
    unregister(hid)
    try:
        code, mods = parse(combo)
    except ValueError as e:
        return str(e)
    ref = c_void_p()
    err = _carbon.RegisterEventHotKey(code, mods, EventHotKeyID(_SIG, hid), _carbon.GetApplicationEventTarget(),
                                      0, byref(ref))
    if err:
        return f"{combo} is taken by another app (error {err})"
    _refs[hid] = ref
    _callbacks[hid] = fn
    return None


def unregister(hid):
    ref = _refs.pop(hid, None)
    _callbacks.pop(hid, None)
    if ref:
        _carbon.UnregisterEventHotKey(ref)
