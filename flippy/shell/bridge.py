"""The only way the app window's page reaches Python: a fixed set of operations on plain JSON.

The page sends {"id": n, "op": name, "args": {...}}; handle() answers {"id": n, "ok": true, "result": ...} or
{"id": n, "ok": false, "error": "..."}. Nothing here runs code, opens paths or URLs the page names: settings
go through settings.set (which validates), commands must be in COMMANDS, and files only come and go through the
platform's own open and save panels (Host).
"""
import os
import time

from .. import settings
from . import appearance, schema, setup

COMMANDS = {"preview", "reset", "tour", "update"}  # daemon commands the page may ask for
MAX_MESSAGE = 4 * 1024 * 1024                       # a smooth drawing's PNG is the biggest thing the page sends


def _version():
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "VERSION")) as f:
            return f.read().strip()[:20]
    except OSError:
        return None


def _check_shortcut(combo):
    """A recorded shortcut must be one the hotkey code can register: a key and at least one modifier."""
    if not isinstance(combo, str) or "+" not in combo:
        raise ValueError("A shortcut needs a modifier, like ⌘ or ⌃.")
    if schema.platform() == "darwin":
        from ..mac import hotkeys
        hotkeys.parse(combo)  # raises ValueError for keys it can't register


class Host:
    """What the platform window provides: the clipboard, file panels, the screen color picker. Defaults do nothing."""
    def copy_text(self, text):
        return False

    def save_file(self, suggested, data, kind):
        """Ask where to save data; True when saved."""
        return False

    def open_file(self, kinds):
        """Ask for a file; (filename, bytes) or None."""
        return None

    def sample_color(self, done):
        """Let the user pick a color anywhere on screen; done("#rrggbb") or done(None)."""
        done(None)

    def set_chrome(self, mode):
        """The page is showing "light" or "dark": match the window's own frame to it."""

    def setup_state(self):
        """The platform's setup checks: claude, codex, screen, accessibility, login_item... (flippy/mac/setup.py)."""
        return {}

    def setup_action(self, name):
        raise ValueError("setup isn't available here")

    def close(self):
        """Close the window (Setup's Done)."""


class Bridge:
    def __init__(self, push=lambda event, data: None, command=lambda cmd: None, log=lambda msg: None, host=None):
        self.push = push          # push(event, data): send an event to the page
        self.command = command    # run one of COMMANDS in the daemon
        self.log = log
        self.host = host or Host()
        self.opened = time.monotonic()
        self.marks = {}
        self.route = None         # where the page opens; later routes are pushed
        self.current = None       # the route the page is showing (op_route)
        self.on_demo_saved = None  # the scripted pointer demo's callback (flippy/demos.py)
        self.demo = None
        self._mark = None
        settings.on_change(self._changed)

    def close(self):
        settings.off_change(self._changed)

    def _changed(self, section, key, *_):
        if (section, key) in settings.SETTINGS and (f := schema.field(section, key)) is not None:
            self.push("setting", f)

    def handle(self, message):
        mid = message.get("id") if isinstance(message, dict) else None
        try:
            if not isinstance(message, dict) or not isinstance(message.get("op"), str):
                raise ValueError("bad message")
            op, args = message["op"], message.get("args") or {}
            if not isinstance(args, dict):
                raise ValueError("bad args")
            fn = getattr(self, "op_" + op, None)
            if fn is None:
                raise ValueError(f"unknown op {op}")
            return {"id": mid, "ok": True, "result": fn(**args)}
        except (TypeError, ValueError, KeyError, OSError) as e:
            return {"id": mid, "ok": False, "error": str(e)}

    # ---- settings
    def op_state(self):
        demo, self.demo = self.demo, None  # a pointer demo asked for before the page loaded
        return {"platform": schema.platform(), "pages": schema.pages(), "route": self.route, "version": _version(),
                "demo": demo}

    def _key(self, id):  # noqa: A002
        section, _, key = str(id).partition(".")
        if (section, key) not in settings.SETTINGS or (section, key) in schema.HIDDEN:
            raise ValueError(f"unknown setting {id}")
        return section, key

    def op_set(self, id, value):  # noqa: A002 (id is the field id the page knows)
        section, key = self._key(id)
        if schema.control(section, key) == "shortcut":
            _check_shortcut(value)
        settings.set(section, key, value)  # raises ValueError when invalid
        return schema.field(section, key)

    def op_set_many(self, values):
        """Several settings at once (undo, reset); all are checked before any is saved."""
        if not isinstance(values, dict):
            raise ValueError("bad values")
        keys = {i: self._key(i) for i in values}
        for i, (section, key) in keys.items():
            if not settings._valid(section, key, values[i]):
                raise ValueError(f"invalid setting {i}")
        for i, (section, key) in keys.items():
            settings.set(section, key, values[i])
        return [schema.field(*k) for k in keys.values()]

    def op_reset(self, page):
        """Put a page's settings back to their defaults; returns the old values, for undo."""
        p = next((p for p in schema.pages() if p["id"] == page), None)
        if p is None:
            raise ValueError(f"unknown page {page}")
        before = {f["id"]: f["value"] for f in p["fields"]}
        self.op_set_many({f["id"]: f["default"] for f in p["fields"]})
        return before

    def op_command(self, name):
        if name not in COMMANDS:
            raise ValueError(f"command not allowed: {name}")
        return self.command(name)

    def op_chrome(self, mode):
        if mode not in ("light", "dark"):
            raise ValueError("bad mode")
        self.host.set_chrome(mode)

    def op_route(self, route):
        self.current = str(route)[:100]

    def op_setup_state(self):
        out = setup.page_state(self.host.setup_state())
        if self._mark is None:
            self._mark = (setup.mark(), setup.logos())
        out["mark"], out["logos"] = self._mark
        return out

    def op_setup_action(self, name):
        self.host.setup_action(str(name))
        return self.op_setup_state()

    def op_close(self):
        self.host.close()

    def start_pointer_demo(self, name, on_saved):
        """Draw a demo pointer in the studio, then on_saved("custom:<name>")."""
        from .. import pixelart
        self.on_demo_saved = on_saved
        self.demo = {"name": name, "sprite": pixelart.DEMO_SPRITE,
                     "colors": {k: pixelart.to_hex(v) for k, v in pixelart.DEMO_COLORS.items()}}
        self.push("demo-pointer", self.demo)  # if the page is already up; else it reads self.demo when it loads

    def op_demo_saved(self, value):
        self.demo = None
        if self.on_demo_saved:
            done, self.on_demo_saved = self.on_demo_saved, None
            done(value)

    def op_mark(self, name):
        """Timing marks from the page (first paint, ready), in ms since the window was asked for."""
        ms = round((time.monotonic() - self.opened) * 1000)
        self.marks[str(name)[:32]] = ms
        self.log(f"app window: {name} at {ms} ms")
        return ms

    # ---- appearance
    def op_gallery(self):
        return {"themes": appearance.themes_gallery(), "pointers": appearance.pointers_gallery()}

    def op_pointers(self):
        return appearance.pointers_gallery()

    def op_studio_open(self, name=None, start=None):
        return appearance.studio_open(name, start)

    def op_studio_template(self, kind):
        if kind not in ("hand", "arrow"):
            raise ValueError("bad template")
        return appearance.template(kind)

    def op_studio_save(self, mode, name, hotspot, flip=True, editing=None, cells=None, image=None, crisp=False):
        value = appearance.studio_save(mode, name, hotspot, flip, editing, cells, image, crisp)
        settings.set("look", "pointer", value)
        return value

    def op_pointer_rename(self, name, new):
        return appearance.rename(name, new)

    def op_pointer_duplicate(self, name):
        return appearance.duplicate(name)

    def op_pointer_delete(self, name):
        appearance.delete(name)

    def op_pointer_export(self, name):
        return self.host.save_file(f"{name}.png", appearance.export_png(name), "png")

    def op_pointer_import(self):
        picked = self.host.open_file(["png", "jpg", "jpeg", "gif", "webp", "tiff", "bmp"])
        if picked is None:
            return None
        filename, data = picked
        result = appearance.import_file(data, filename)
        if result.get("saved"):
            settings.set("look", "pointer", result["saved"])
        return result

    def op_eyedropper(self):
        self.host.sample_color(lambda hex_color: self.push("color", hex_color))

    def op_look_copy(self):
        text = appearance.export_look()
        return {"copied": bool(self.host.copy_text(text)), "text": text}

    def op_look_import(self, text):
        if not isinstance(text, str) or len(text) > MAX_MESSAGE:
            raise ValueError("bad look")
        return appearance.apply_look(text)
