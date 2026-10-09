"""When the setup window opens by itself: on a new install, on a new major version (X.0.0), and when the
subscription needs logging in again. Any other time it opens only from the menu ("Setup…").

The major version setup was last shown for lives in <config dir>/setup.json. People who used Flippy before
this file existed count as already set up, so an ordinary update doesn't reopen it.
"""
import json
import os

from . import settings, updates
from .profile import current

PATH = os.path.join(current().config_dir, "setup.json")
_USED_BEFORE = os.path.exists(settings.PATH)  # read at import, before this run saves anything


def _major(version):
    try:
        return int(str(version).split(".")[0])
    except ValueError:
        return 0


def _seen():
    try:
        with open(PATH) as f:
            value = json.load(f).get("major")
        return value if type(value) is int else None
    except (OSError, ValueError, AttributeError):
        return None


def mark_seen():
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"major": _major(updates.current_version())}, f)
    os.replace(tmp, PATH)


def relogin_needed(status, mode):
    """The subscription Flippy would use is known to be logged out (None = not checked yet, never a reason)."""
    if mode == "auto":
        return status.get("claude") is False and status.get("codex") is False
    return status.get(mode) is False


def launch_reason(status, mode):
    """Why setup should open now that the first login check is done: "install", "major", "relogin" or None."""
    seen = _seen()
    if seen is None and _USED_BEFORE:
        mark_seen()  # an existing user meeting this file for the first time
        seen = _seen()
    if seen is None:
        return "install"
    if _major(updates.current_version()) > seen:
        return "major"
    if relogin_needed(status, mode):
        return "relogin"
    return None


def login_error(err, status, mode):
    """Did this failed request fail because the subscription needs logging in again?"""
    from .errors import LOGIN_CODES, code_of
    return code_of(err) in LOGIN_CODES
