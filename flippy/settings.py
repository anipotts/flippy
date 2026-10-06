"""User settings: ~/.config/flippy/config.toml, with defaults for anything missing.

Everything adjustable lives here. The settings window edits it live and the
daemon reacts through on_change listeners; hand-editing the file works too
(it's read at startup). A broken file falls back to defaults instead of crashing.
"""
import copy
import os
import tomllib

PATH = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "flippy", "config.toml")

DEFAULTS = {
    "claude": {
        "model": "default",     # default | opus | sonnet | haiku
        "effort": "low",        # low | medium | high | max
        "image": 1920,          # screenshot long edge sent to Claude: 1366 | 1920 | 0 (full)
    },
    "look": {
        "theme": "midnight",    # see flippy/themes.py
        "pointer": "theme",     # theme | hand | ring | arrow | dot | glass | glasshand
        "pointer_size": 1.0,    # multiplier
        "text_size": 15,        # px, answer text
        "card_opacity": 0.94,
        "controls": "all",      # all | players (playback controls on every theme, or only Glass/Y2K)
        "glass_shine": "wmp",   # wmp | none: gloss bars on the Glass theme's Liquid Glass (macOS), or plain glass
    },
    "timing": {
        "show_seconds": 8,      # answer stays at least this long after it finishes
        "max_show_seconds": 20,
        "step_pace": "normal",  # slow | normal | fast (how long each walkthrough step holds)
        "glide_seconds": 0.6,   # hand travel time between points
        "speed": 1.0,           # walkthrough playback speed, 0.5-2.0 (the player skins' speed slider)
    },
    "help": {                   # help mode (flippy/watch.py): offer a hand when you seem stuck
        "mode": "off",          # off | quiet (offer a hand when stuck) | tips (that, plus cached tips: flippy/tips.py)
        "apps": "",             # comma-separated app ids to watch (macOS bundle ids)
        "muted": "",            # apps where you chose "don't ask"
    },
    "automation": {
        "clicks": False,        # let `flippy-ask click` click on screen (macOS: needs the Accessibility permission)
    },
    "keys": {                   # global hotkeys (macOS; on COSMIC they're set in COSMIC Settings)
        "ask": "cmd+shift+space",
        "draw": "ctrl+shift+space",
    },
}

CHOICES = {
    ("claude", "model"): ["default", "opus", "sonnet", "haiku"],
    ("claude", "effort"): ["low", "medium", "high", "max"],
    ("claude", "image"): [1366, 1920, 0],
    ("look", "theme"): ["midnight", "y2k", "glass", "nowplaying", "terminal", "cosmic"],  # keep in sync with themes.THEMES
    ("look", "pointer"): ["theme", "hand", "ring", "arrow", "dot", "glass", "glasshand"],
    ("look", "controls"): ["all", "players"],
    ("look", "glass_shine"): ["wmp", "none"],
    ("timing", "step_pace"): ["slow", "normal", "fast"],
    ("help", "mode"): ["off", "quiet", "tips"],
}

_data = copy.deepcopy(DEFAULTS)
_listeners = []


def load():
    global _data
    data = copy.deepcopy(DEFAULTS)
    try:
        with open(PATH, "rb") as f:
            user = tomllib.load(f)
        for section, values in user.items():
            if section in data and isinstance(values, dict):
                for k, v in values.items():
                    if k in data[section] and _valid(section, k, v):
                        data[section][k] = v
    except FileNotFoundError:
        pass
    except (tomllib.TOMLDecodeError, OSError) as e:
        print(f"flippy: ignoring broken {PATH}: {e}", flush=True)
    _data = data


def _valid(section, key, value):
    default = DEFAULTS[section][key]
    if isinstance(default, bool) != isinstance(value, bool):
        return False
    if isinstance(default, (int, float)) and not isinstance(default, bool):
        if not isinstance(value, (int, float)):
            return False
    elif type(value) is not type(default):
        return False
    if (section, key) == ("look", "pointer") and value.startswith("custom:"):
        from . import pointers  # local: keep this module light
        return pointers.exists(value[len("custom:"):])
    choices = CHOICES.get((section, key))
    return choices is None or value in choices


def get(section, key):
    return _data[section][key]


def get_list(section, key):
    """A comma-separated string setting as a set."""
    return {v.strip() for v in _data[section][key].split(",") if v.strip()}


def set_list(section, key, values):
    set(section, key, ",".join(sorted(values)))


def set(section, key, value):  # noqa: A001 (module-level API reads nicely as settings.set)
    if _data[section].get(key) == value:
        return
    _data[section][key] = value
    save()
    for fn in list(_listeners):
        fn(section, key, value)


def on_change(fn):
    _listeners.append(fn)


def off_change(fn):
    if fn in _listeners:
        _listeners.remove(fn)


def save():
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    lines = ["# Flippy settings. Edit here or via `flippy-ask settings`.\n"]
    for section, values in _data.items():
        lines.append(f"\n[{section}]\n")
        for k, v in values.items():
            lines.append(f"{k} = {_toml(v)}\n")
    tmp = PATH + ".tmp"
    with open(tmp, "w") as f:
        f.writelines(lines)
    os.replace(tmp, PATH)


def _toml(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(round(v, 3)) if isinstance(v, float) else str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


load()
