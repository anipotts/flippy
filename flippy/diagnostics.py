"""Content-free diagnostics by default; recording is an explicit process option."""
import json
import os
import stat
import time

SECRET_FIELDS = frozenset({'token', 'access_token', 'refresh_token', 'id_token', 'api_key', 'authorization', 'password', 'cookie', 'credentials'})

SAFE_FIELDS = frozenset({'request_id', 'mode', 'outcome', 'duration_ms', 'count', 'n',
                         'control', 'reason_code', 'drag', 'key'})

CONTROLS = frozenset({'stop', 'close', 'min', 'speed', 'speed_cycle', 'toggle', 'pause', 'play', 'prev', 'next', 'seek'})
HOTKEYS = frozenset({'ask', 'draw', 'pause', 'reset', 'dismiss', 'quit'})
RECORD_FIELDS = SAFE_FIELDS | frozenset({'question', 'text', 'label', 'ch', 'path', 'name', 'x', 'y', 'x0', 'y0', 'x1', 'y1', 'tutorial', 'app', 'reason', 'combo'})

class Diagnostics:
    def __init__(self, path, *, record_content=False, clock=time.time):
        self.path = path
        self.record_content = record_content
        self.clock = clock

    def event(self, name, **data):
        # Even recording cannot accidentally serialize a credential-bearing object.
        allowed_keys = RECORD_FIELDS if self.record_content else SAFE_FIELDS
        allowed = {k: v for k, v in data.items() if k in allowed_keys}
        values = {k: v for k, v in allowed.items()
                  if k.lower() not in SECRET_FIELDS and (isinstance(v, (str, int, float, bool)) or v is None)}
        if 'control' in values and values['control'] not in CONTROLS:
            values.pop('control')
        if 'key' in values and values['key'] not in HOTKEYS:
            values.pop('key')
        record = {'t': self.clock(), 'ev': name, **values}
        try:
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
            fd = os.open(self.path, flags, 0o600)
            with os.fdopen(fd, 'w') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): return
                os.fchmod(stream.fileno(), 0o600)
                stream.write(json.dumps(record, allow_nan=False) + '\n')
        except (OSError, ValueError, TypeError):
            pass

    def command(self, command):
        # Never log arguments, including /act tasks and typed text.
        verb = command.split(maxsplit=1)[0] if command.strip() else ''
        self.event('command', reason_code=verb if verb in COMMANDS else 'unknown')

COMMANDS = frozenset('ask draw video settings setup preview control set dismiss reset quit pause-toggle update version ping help-mode click move path type key tap hotkey goal watch-app q act'.split())
