"""Updates: when a newer GitHub Release is out, offer to install it.

An install is either a git checkout (install.sh) or a release download
(flippy-<version>-macos.tar.gz / -linux.tar.gz, made by scripts/package.sh, with a
PACKAGE file naming its platform). A checkout updates by fast-forwarding to the
latest main; a download fetches its platform's file from the latest release and
unpacks it over itself. Either way the Python packages are reinstalled if the
requirements changed. Releases (tags like v0.3, made with scripts/release.sh)
decide what counts as a new version: pushing to main alone doesn't prompt anyone.

The check is one unauthenticated request to the GitHub API, at most once a day
(settings: updates.check). Nothing about the user is sent.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
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
    return current_version_at(ROOT)


def current_version_at(root):
    try:
        with open(os.path.join(root, "VERSION")) as f:
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
            "notes": (d.get("body") or "").strip(), "url": d.get("html_url", ""),
            "assets": {a["name"]: a["browser_download_url"] for a in d.get("assets") or [] if "name" in a}}


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


def platform_name():
    return "macos" if sys.platform == "darwin" else "linux"


def package_platform(root=ROOT):
    """'macos' / 'linux' for a release download, None for a git checkout."""
    try:
        with open(os.path.join(root, "PACKAGE")) as f:
            return f.read().strip() or None
    except OSError:
        return None


def blocked(root=ROOT):
    """Why this copy can't update itself, or None."""
    if not os.path.isdir(os.path.join(root, ".git")):
        if package_platform(root):
            return None
        return "this copy of Flippy isn't a git checkout or a release download"
    if _git("rev-parse", "--abbrev-ref", "HEAD", root=root) != "main":
        return "this copy is on a branch other than main"
    if _git("status", "--porcelain", "--untracked-files=no", root=root):
        return "this copy has local changes; update it yourself with git pull"
    return None


def requirements_file():
    return "requirements-mac.txt" if sys.platform == "darwin" else "requirements-linux.txt"


# the parts of a release download that are Flippy's (replaced on update); everything else (.venv) is left alone
PACKAGE_DIRS = ("bin", "flippy", "packaging", "scripts", "docs")


def _files(root):
    """{relative path: sha256} of Flippy's own files in a release download."""
    out = {}
    for top in os.listdir(root):
        full = os.path.join(root, top)
        if os.path.isfile(full):
            paths = [top]
        elif top in PACKAGE_DIRS:
            paths = [os.path.relpath(os.path.join(d, n), root) for d, dirs, names in os.walk(full)
                     if "__pycache__" not in d for n in names]
        else:
            continue
        for rel in paths:
            with open(os.path.join(root, rel), "rb") as f:
                out[rel] = hashlib.sha256(f.read()).hexdigest()
    return out


def _download(url, dest, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "flippy-updater"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
    except (OSError, urllib.error.URLError) as e:
        raise UpdateError(f"couldn't download the update ({e})") from e


def unpack(archive, root, log=print):
    """Unpack a release download (one top folder inside) over root. Returns the changed paths."""
    before = _files(root)
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(archive) as tar:
            if hasattr(tarfile, "data_filter"):
                tar.extractall(tmp, filter="data")  # no absolute paths, .., devices or links out of tmp
            else:
                for m in tar.getmembers():
                    if m.name.startswith("/") or ".." in m.name.split("/") or not (m.isfile() or m.isdir()):
                        raise UpdateError(f"unexpected file in the update: {m.name}")
                tar.extractall(tmp)
        tops = os.listdir(tmp)
        if len(tops) != 1 or not os.path.isfile(os.path.join(tmp, tops[0], "flippy", "daemon.py")):
            raise UpdateError("the update doesn't look like Flippy")
        src = os.path.join(tmp, tops[0])
        if package_platform(src) != package_platform(root):
            raise UpdateError(f"the update is for {package_platform(src)}, this copy is {package_platform(root)}")
        new = _files(src)
        for rel in new:
            if before.get(rel) != new[rel]:
                os.makedirs(os.path.dirname(os.path.join(root, rel)) or root, exist_ok=True)
                shutil.copy2(os.path.join(src, rel), os.path.join(root, rel))
        for rel in set(before) - set(new):  # files the new version dropped
            if rel.split(os.sep)[0] in PACKAGE_DIRS:
                os.unlink(os.path.join(root, rel))
    log(f"update: unpacked {archive}")
    return sorted(rel for rel in set(before) | set(new) if before.get(rel) != new.get(rel))


def install(root=ROOT, log=print):
    """Update to the latest: fast-forward a checkout to origin/main, or unpack the latest release over a download;
    reinstall packages if the requirements changed.
    Returns {'from', 'to', 'packages', 'app'}: app = the macOS launcher changed (needs ./install.sh)."""
    why = blocked(root)
    if why:
        raise UpdateError(why)
    if package_platform(root):
        before = current_version_at(root)
        rel = latest_release()
        if not rel or not is_newer(rel["version"], before):
            return {"from": before, "to": before, "packages": False, "app": False}
        name = f"flippy-{rel['version']}-{package_platform(root)}.tar.gz"
        url = rel.get("assets", {}).get(name)
        if not url:
            raise UpdateError(f"the {rel['version']} release has no {name}")
        log(f"update: downloading {name}")
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, name)
            _download(url, archive)
            changed = unpack(archive, root, log)
        after = current_version_at(root)
    else:
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
