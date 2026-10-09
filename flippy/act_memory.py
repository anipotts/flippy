"""What worked in each app, so the next /act task starts with the right tool instead of walking down the list.

Two things per app (by bundle id), in ~/.config/flippy/act_memory.json:
  route  the acting steps of the last task that finished in that app, by tool only:
         ["app_action spotify.open_search", "click", "click (real pointer)"]
  failed how often each tool came back "Not done" there ({"press": 3})
  how    a one-line how-to the task wrote with the remember tool ("play a song: app_action spotify.open_search,
         then click the Top result's play button with real_pointer true; background clicks are ignored")

Steps are tool names (plus the fixed app_action / media action name), never their text, coordinates or the task.
The how-to is the model's own words, told to describe the app, not the user's request. Delete the file to forget.
"""
import json
import os
import tempfile
import time

from .profile import current

PATH = os.path.join(current().config_dir, "act_memory.json")
MAX_APPS = 40
MAX_ROUTE = 8
MAX_HOW = 300


def step_name(name, args):
    """One step as remembered: the tool, the fixed action it ran, and whether it borrowed the pointer."""
    label = name + (f" {args.get('action')}" if name in ("app_action", "media") and isinstance(args, dict) else "")
    return label + (" (real pointer)" if isinstance(args, dict) and args.get("real_pointer") is True else "")


def load():
    try:
        with open(PATH) as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, dict)}
    except (OSError, ValueError, AttributeError):
        return {}


def _save(data):
    if len(data) > MAX_APPS:  # keep the most recently used apps
        data = dict(sorted(data.items(), key=lambda kv: kv[1].get("used", 0))[-MAX_APPS:])
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".act_memory-", suffix=".tmp", dir=os.path.dirname(PATH))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        os.replace(tmp, PATH)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def record(journal, notes, names, finished):
    """Fold one task in. journal: [(bundle, step, ok)]; notes: {bundle: how}; names: {bundle: app name};
    finished: the task ended without stopping, so its route is worth repeating."""
    if not journal and not notes:
        return
    data = load()
    now = int(time.time())
    routes = {}
    for bundle, step, ok in journal:
        entry = data.setdefault(bundle, {})
        entry["used"] = now
        if ok:
            routes.setdefault(bundle, []).append(step)
        else:
            failed = entry.setdefault("failed", {})
            failed[step] = failed.get(step, 0) + 1
    if finished:
        for bundle, steps in routes.items():
            data[bundle]["route"] = steps[-MAX_ROUTE:]
    for bundle, how in notes.items():
        data.setdefault(bundle, {}).update(how=how[:MAX_HOW], used=now)
    for bundle, name in names.items():
        if bundle in data and name:
            data[bundle]["name"] = name
    _save(data)


def brief(data=None):
    """The prompt section: per app, the note, the last route and what didn't work. Empty when nothing's known."""
    data = load() if data is None else data
    lines = []
    for bundle, entry in sorted(data.items(), key=lambda kv: -kv[1].get("used", 0)):
        parts = []
        if isinstance(entry.get("how"), str):
            parts.append("how: " + entry["how"])
        if isinstance(entry.get("route"), list) and entry["route"]:
            parts.append("last time that finished: " + " -> ".join(map(str, entry["route"])))
        failed = entry.get("failed") if isinstance(entry.get("failed"), dict) else {}
        misses = [f"{step} (x{n})" for step, n in sorted(failed.items(), key=lambda kv: -kv[1]) if n >= 2]
        if misses:
            parts.append("often not done here: " + ", ".join(misses[:5]))
        if parts:
            lines.append(f"- {entry.get('name') or bundle} ({bundle}): " + "; ".join(parts))
    if not lines:
        return ""
    return ("\nWhat you learned in earlier tasks, per app. Start with what worked there instead of going down the "
            "list from the top; skip ways that are often not done. Still check the result, and if the remembered way "
            "fails now, fall back to the list.\n" + "\n".join(lines) + "\n")
