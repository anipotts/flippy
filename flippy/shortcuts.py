"""Which of Flippy's shortcuts won't work, and why: for the tour's first step, the menus and setup.

  macOS: a combo another app registered first (Carbon says so), a macOS shortcut on the same keys (Spotlight,
         input sources, screenshots: the system gets it first, and Carbon doesn't tell us), a combo many apps
         use themselves (⇧⌘V is Paste and Match Style), or double-tap without the Accessibility permission.
  COSMIC: a Flippy action with no shortcut, or one whose keys COSMIC (or another custom shortcut) also uses.

Platform.shortcut_problems() returns {name: reason or None} for NAMES; no GUI here, so it's testable anywhere.
"""
import os
import plistlib
import re

NAMES = ("ask", "draw", "video", "pause")
TITLES = {"ask": "Ask", "draw": "Circle", "video": "Video review", "pause": "Pause"}

# ---- macOS

SYMBOLIC = os.path.expanduser("~/Library/Preferences/com.apple.symbolichotkeys.plist")
# AppleSymbolicHotKeys ids worth naming (the rest are "a macOS shortcut")
SYMBOLIC_NAMES = {
    28: "Screenshot", 29: "Screenshot to clipboard", 30: "Screenshot of an area", 31: "Screenshot of an area to "
    "clipboard", 184: "Screenshot and recording options", 32: "Mission Control", 33: "Application windows",
    36: "Show Desktop", 60: "Previous input source", 61: "Next input source", 64: "Spotlight",
    65: "Finder search", 79: "Move left a space", 81: "Move right a space", 118: "Switch to Desktop 1",
    160: "Launchpad", 162: "Accessibility controls", 163: "Notification Center", 175: "Do Not Disturb",
    190: "Quick Note", 222: "Stage Manager",
}
# macOS's own defaults for the common ones: in effect even when the plist doesn't list them yet
SYMBOLIC_DEFAULTS = {64: (49, 1 << 20), 65: (49, (1 << 20) | (1 << 19)), 60: (49, 1 << 18), 61: (49, (1 << 18) | (1 << 19)),
                     28: (20, (1 << 20) | (1 << 17)), 30: (21, (1 << 20) | (1 << 17)), 184: (23, (1 << 20) | (1 << 17))}
# combos apps commonly use for themselves: Flippy's hotkey would take them away from every app
APP_COMBOS = {"cmd+shift+v": "Paste and Match Style in many apps", "cmd+option+shift+v": "Paste and Match Style "
              "in many apps", "cmd+shift+z": "Redo", "cmd+shift+s": "Save As", "cmd+shift+n": "New Folder / new "
              "window", "cmd+shift+t": "Reopen closed tab", "cmd+shift+4": "Screenshot of an area",
              "cmd+shift+3": "Screenshot", "cmd+shift+5": "Screenshot and recording options"}
# Carbon modifier bits (hotkeys.MODS) -> the NSEvent flag bits the symbolic hotkeys plist uses
CARBON_TO_NS = {1 << 8: 1 << 20, 1 << 9: 1 << 17, 1 << 11: 1 << 19, 1 << 12: 1 << 18}
NS_MASK = (1 << 17) | (1 << 18) | (1 << 19) | (1 << 20)


def ns_mods(carbon_mods):
    return sum(ns for carbon, ns in CARBON_TO_NS.items() if carbon_mods & carbon)


def system_shortcuts(path=SYMBOLIC):
    """{(key code, NSEvent modifier bits): name} of the enabled macOS shortcuts."""
    try:
        with open(path, "rb") as f:
            table = plistlib.load(f).get("AppleSymbolicHotKeys", {})
    except (OSError, ValueError, plistlib.InvalidFileException):
        table = {}
    out = {}
    for hid, (code, mods) in SYMBOLIC_DEFAULTS.items():
        entry = table.get(str(hid))
        if entry is None or entry.get("enabled", True):  # still on (the plist only lists changed ones)
            if entry is None or not (entry.get("value") or {}).get("parameters"):
                out[(code, mods)] = SYMBOLIC_NAMES.get(hid, "a macOS shortcut")
    for hid, entry in table.items():
        params = ((entry or {}).get("value") or {}).get("parameters") or []
        if not (entry or {}).get("enabled") or len(params) < 3 or params[1] == 65535:
            continue
        out[(int(params[1]), int(params[2]) & NS_MASK)] = SYMBOLIC_NAMES.get(int(hid), "a macOS shortcut")
    return out


def mac_problem(combo, parse, register_error=None, system=None):
    """Why combo ("cmd+shift+space") won't work as a Flippy hotkey, or None. parse: hotkeys.parse."""
    if register_error:
        return register_error
    try:
        code, mods = parse(combo)
    except ValueError as e:
        return str(e)
    clash = (system if system is not None else system_shortcuts()).get((code, ns_mods(mods)))
    if clash:
        return f"macOS uses it for {clash}"
    def keys(c):  # modifiers in any order
        *mods, key = c.lower().split("+")
        return sorted(mods), key
    what = next((what for other, what in APP_COMBOS.items() if keys(other) == keys(combo)), None)
    return f"it's {what}" if what else None


# ---- COSMIC (RON files: `(modifiers: [Super, Shift], key: "space"): Spawn("...")`)

COSMIC_DIR = "com.system76.CosmicSettings.Shortcuts/v1"
COSMIC_DEFAULTS = ("/usr/share/cosmic/" + COSMIC_DIR + "/defaults",)
COSMIC_SYSTEM = os.path.expanduser("~/.config/cosmic/" + COSMIC_DIR + "/system_actions")
BINDING_RE = re.compile(r'\(\s*modifiers:\s*\[([^\]]*)\]\s*,?(?:\s*key:\s*"([^"]+)"\s*,?)?\s*\):\s*'
                        r'((?:\w+)(?:\((?:[^()"]|"[^"]*"|\([^()]*\))*\))?)')
WANTS = {"ask": ("", "ask"), "draw": ("draw",), "video": ("video",), "pause": ("pause-toggle",)}


def cosmic_bindings(text):
    """[(frozenset of modifiers, key or "", action)] from a COSMIC shortcuts file."""
    out = []
    for m in BINDING_RE.finditer(text or ""):
        mods = frozenset(x.strip().lower().replace("control", "ctrl") for x in m.group(1).split(",") if x.strip())
        out.append((mods, (m.group(2) or "").lower(), m.group(3)))
    return out


def _flippy_args(action):
    m = re.match(r'Spawn\("[^"]*flippy-ask([^"]*)"\)', action)
    return m.group(1).strip() if m else None


def _describe(action):
    m = re.match(r'(\w+)(?:\((.*)\))?$', action, re.S)
    inner = (m.group(2) or "").strip().strip('"') if m else ""
    if m and m.group(1) == "Spawn":
        return f"the shortcut that runs {inner.split('/')[-1] or 'a command'}"
    return f"COSMIC's {re.sub(r'(?<!^)(?=[A-Z])', ' ', inner or (m.group(1) if m else action)).lower()} shortcut"


def cosmic_problems(custom_text, system_texts=()):
    """{name: reason or None} for NAMES, from the custom shortcuts file and COSMIC's own (defaults, overrides)."""
    custom = cosmic_bindings(custom_text)
    others = [b for b in custom if _flippy_args(b[2]) is None]
    for text in system_texts:
        others += [b for b in cosmic_bindings(text) if b[2] != "Disable"]
    out = {}
    for name in NAMES:
        mine = [b for b in custom if _flippy_args(b[2]) in WANTS[name]]
        if not mine:
            out[name] = "it isn't set up yet"
            continue
        mods, key, _ = mine[0]
        clash = next((b for b in others if b[0] == mods and b[1] == key), None)
        out[name] = f"it's also {_describe(clash[2])}" if clash else None
    return out


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""
