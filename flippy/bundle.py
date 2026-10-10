"""The self-contained Flippy.app's contract with the code it runs (scripts/build_app.sh, packaging/macos/Launcher.swift).

The app freezes a runtime: its Python, its packages and its launcher. The code it runs lives outside the app, so
updates never touch the signed bundle and macOS keeps its Screen Recording and Accessibility grants:

    ~/Library/Application Support/Flippy/
        code -> versions/1760000000000-0.3.1     a symlink, swapped atomically
        versions/<ms>-<version>/                 one folder per installed copy; the launcher keeps the previous one
            RUNTIME                              the runtime this copy was checked against
        .lock                                    held by the launcher and the updater while they change the layout

Which runtime a release needs is a fingerprint of the files that decide what the app has to contain
(RUNTIME_FILES). The app records its own in Info.plist (FlippyRuntime) and passes it to the daemon. A release with
a different fingerprint needs a new Flippy.dmg; one with the same fingerprint installs as a new folder and becomes
current with one rename, so a failed or interrupted update leaves the running copy whole.

The launcher reads only strings from this layout (the link and RUNTIME): this module is the one place that
computes fingerprints, and build_app.sh calls it too, so the app and the updater can't disagree.
"""
import fcntl
import hashlib
import os
import shutil
import time
from contextlib import contextmanager

# What the app freezes: its packages, the launcher compiled into it, and the pinned Python and native libraries.
RUNTIME_FILES = ("requirements-mac.txt", "packaging/macos/Launcher.swift", "packaging/macos/runtime.env")


class BundleError(Exception):
    pass


def runtime_id(code):
    """The fingerprint of the runtime the code at `code` needs (hex sha256 over RUNTIME_FILES)."""
    h = hashlib.sha256()
    for rel in RUNTIME_FILES:
        try:
            with open(os.path.join(code, rel), "rb") as f:
                data = f.read()
        except OSError as e:
            raise BundleError(f"not a macOS release: {rel} is missing") from e
        h.update(rel.encode() + b"\0" + str(len(data)).encode() + b"\0" + data)
    return h.hexdigest()


def recorded_runtime(code):
    """The runtime a copy was checked against when it was installed, or None."""
    try:
        with open(os.path.join(code, "RUNTIME")) as f:
            return f.read().strip() or None
    except OSError:
        return None


def next_name(versions, version):
    """'<ms>-<version>': the time in ms, but always after every copy already there, so the order is the order they
    were installed in (the launcher keeps the newest)."""
    taken = [int(n.split("-", 1)[0]) for n in os.listdir(versions) if n.split("-", 1)[0].isdigit()]
    return f"{max([time.time_ns() // 1_000_000] + [t + 1 for t in taken])}-{version}"


@contextmanager
def locked(home):
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, ".lock"), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def activate(home, src, runtime):
    """Install the unpacked release at `src` as a new copy under `home` and make it current. `src` is moved, not
    copied. Refuses (changing nothing) unless the release needs exactly `runtime`. Returns the new copy's path."""
    if runtime_id(src) != runtime:
        raise BundleError("this release needs a different app")
    with open(os.path.join(src, "VERSION")) as f:
        version = f.read().strip()
    versions = os.path.join(home, "versions")
    with locked(home):
        os.makedirs(versions, exist_ok=True)
        name = next_name(versions, version)
        staging = os.path.join(versions, ".staging-" + name)
        shutil.move(src, staging)
        with open(os.path.join(staging, "RUNTIME"), "w") as f:
            f.write(runtime + "\n")
        slot = os.path.join(versions, name)
        os.rename(staging, slot)
        link = os.path.join(home, "code")
        tmp = link + ".new"
        if os.path.lexists(tmp):
            os.unlink(tmp)
        os.symlink(os.path.join("versions", name), tmp)
        os.replace(tmp, link)  # atomic: anything starting Flippy sees the old copy or the new one, never neither
    return slot
