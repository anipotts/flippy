"""The only way the app window's page reaches Python: a fixed set of operations on plain JSON.

The page sends {"id": n, "op": name, "args": {...}}; handle() answers {"id": n, "ok": true, "result": ...} or
{"id": n, "ok": false, "error": "..."}. Nothing here runs code, opens paths or URLs the page names: settings
go through settings.set (which validates), and commands must be in COMMANDS.
"""
import time

from .. import settings
from . import schema

COMMANDS = {"preview", "reset", "tour", "update"}  # daemon commands the page may ask for
MAX_MESSAGE = 64 * 1024


class Bridge:
    def __init__(self, push=lambda event, data: None, command=lambda cmd: None, log=lambda msg: None):
        self.push = push          # push(event, data): send an event to the page
        self.command = command    # run one of COMMANDS in the daemon
        self.log = log
        self.opened = time.monotonic()
        self.marks = {}
        self.route = None         # where the page opens; later routes are pushed
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
        except (TypeError, ValueError, KeyError) as e:
            return {"id": mid, "ok": False, "error": str(e)}

    # ---- operations
    def op_state(self):
        return {"platform": schema.platform(), "pages": schema.pages(), "route": self.route}

    def op_set(self, id, value):  # noqa: A002 (id is the field id the page knows)
        section, _, key = id.partition(".")
        if (section, key) not in settings.SETTINGS or (section, key) in schema.HIDDEN:
            raise ValueError(f"unknown setting {id}")
        settings.set(section, key, value)  # raises ValueError when invalid
        return schema.field(section, key)

    def op_command(self, name):
        if name not in COMMANDS:
            raise ValueError(f"command not allowed: {name}")
        return self.command(name)

    def op_mark(self, name):
        """Timing marks from the page (first paint, ready), in ms since the window was asked for."""
        ms = round((time.monotonic() - self.opened) * 1000)
        self.marks[str(name)[:32]] = ms
        self.log(f"app window: {name} at {ms} ms")
        return ms
