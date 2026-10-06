"""Updates: when a newer GitHub Release is out, offer to install it.

The install is a git checkout (see install.sh), so an update is a fast-forward
of that checkout to the latest main, plus the Python packages if the
requirements changed. Releases (tags like v0.3, made with scripts/release.sh)
decide what counts as a new version: pushing to main alone doesn't prompt anyone.

The check is one unauthenticated request to the GitHub API, at most once a day
(settings: updates.check). Nothing about the user is sent.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REPO = "kap-il/flippy"
STATE = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "flippy", "update.json")
CHECK_EVERY_S = 24 * 3600


class UpdateError(Exception):
    pass


def current_version():
    try:
        with open(os.path.join(ROOT, "VERSION")) as f:
            return f.read().strip()
    except OSError:
        return "0"


def parse_version(v):
    """'v0.3.1' -> (0, 3, 1); anything unparseable sorts lowest."""
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums) or (0,)


def is_newer(latest, current):
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def repo_slug(root=ROOT):
    """owner/name of the GitHub repo this checkout came from (so forks check their own releases)."""
    try:
        url = subprocess.run(["git", "-C", root, "config", "--get", "remote.origin.url"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        url = ""
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else DEFAULT_REPO


def latest_release(slug=None, timeout=10):
    """{'version', 'name', 'notes', 'url'} of the latest GitHub Release, or None if there isn't one."""
    req = urllib.request.Request(f"https://api.github.com/repos/{slug or repo_slug()}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "flippy-updater"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise UpdateError(f"GitHub said {e.code}") from e
    except (OSError, ValueError) as e:
        raise UpdateError(f"couldn't reach GitHub ({e})") from e
    return {"version": d.get("tag_name", "").lstrip("v"), "name": d.get("name") or d.get("tag_name", ""),
            "notes": (d.get("body") or "").strip(), "url": d.get("html_url", "")}


# ---- remembering checks and "Later"
def _state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(st, f)


def due():
    return time.time() - _state().get("checked_at", 0) >= CHECK_EVERY_S


def mark_checked():
    st = _state()
    st["checked_at"] = time.time()
    _save_state(st)


def check(force=False):
    """The release to offer, or None: newer than this install and not put off with "Later" today."""
    rel = latest_release()
    mark_checked()
    if not rel or not is_newer(rel["version"], current_version()):
        return None
    st = _state()
    if not force and st.get("later") == rel["version"] and time.time() - st.get("later_at", 0) < CHECK_EVERY_S:
        return None
    return rel


def later(version):
    st = _state()
    st.update(later=version, later_at=time.time())
    _save_state(st)


# ---- installing
def _git(*args, root=ROOT, timeout=120):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise UpdateError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout) else
                          f"git {args[0]} failed")
    return r.stdout.strip()


def blocked(root=ROOT):
    """Why this checkout can't update itself, or None."""
    if not os.path.isdir(os.path.join(root, ".git")):
        return "this copy of Flippy isn't a git checkout"
    if _git("rev-parse", "--abbrev-ref", "HEAD", root=root) != "main":
        return "this copy is on a branch other than main"
    if _git("status", "--porcelain", "--untracked-files=no", root=root):
        return "this copy has local changes; update it yourself with git pull"
    return None


def requirements_file():
    return "requirements-mac.txt" if sys.platform == "darwin" else "requirements-linux.txt"


def install(root=ROOT, log=print):
    """Fast-forward to origin/main; reinstall packages if the requirements changed.
    Returns {'from', 'to', 'packages', 'app'}: app = the macOS launcher changed (needs ./install.sh)."""
    why = blocked(root)
    if why:
        raise UpdateError(why)
    before = _git("rev-parse", "HEAD", root=root)
    log("update: fetching")
    _git("fetch", "--tags", "origin", "main", root=root)
    _git("merge", "--ff-only", "origin/main", root=root)
    after = _git("rev-parse", "HEAD", root=root)
    changed = _git("diff", "--name-only", before, after, root=root).splitlines() if before != after else []
    req = requirements_file()
    packages = req in changed
    if packages:
        log(f"update: {req} changed, installing packages")
        pip = os.path.join(root, ".venv", "bin", "pip")
        env = dict(os.environ)
        if sys.platform == "darwin":  # pycairo builds against Homebrew's cairo
            env["PKG_CONFIG_PATH"] = "/opt/homebrew/lib/pkgconfig:" + env.get("PKG_CONFIG_PATH", "")
        r = subprocess.run([pip, "install", "-q", "-r", os.path.join(root, req)], capture_output=True, text=True,
                           env=env, timeout=900)
        if r.returncode != 0:
            raise UpdateError("installing packages failed: " + (r.stderr.strip().splitlines() or ["?"])[-1])
    return {"from": before[:7], "to": after[:7], "packages": packages,
            "app": any(f.startswith("packaging/macos/") for f in changed)}
