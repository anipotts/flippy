"""Shared application paths and ownership for normal and isolated demo runs."""
import atexit
import errno
import fcntl
import os
import socket
import stat
import tempfile
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str = "default"

    @property
    def demo(self):
        return self.name == "demo"

    @property
    def slug(self):
        return "flippy-demo" if self.demo else "flippy"

    @property
    def config_dir(self):
        return os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), self.slug)

    @property
    def runtime_dir(self):
        return os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()

    @property
    def socket(self):
        return os.path.join(self.runtime_dir, self.slug + ".sock")

    @property
    def events(self):
        return os.path.join(self.runtime_dir, self.slug + "-events.jsonl")

    @property
    def log(self):
        if __import__("sys").platform == "darwin":
            return os.path.expanduser("~/Library/Logs/" + self.slug + ".log")
        return os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), self.slug + ".log")

    @property
    def app(self):
        return os.path.expanduser("~/Applications/Flippy Demo.app" if self.demo else "~/Applications/Flippy.app")

    @property
    def bundle_id(self):
        return "dev.flippy.demo" if self.demo else "dev.flippy.app"


def current():
    name = os.environ.get("FLIPPY_PROFILE", "default")
    if name not in ("default", "demo"):
        raise ValueError("FLIPPY_PROFILE must be default or demo")
    return Profile(name)


class Instance:
    """A per-profile lock; never unlink an active listener or a non-socket file."""
    def __init__(self, profile):
        self.profile, self.fd = profile, None
        self.socket_identity = None

    def acquire(self):
        path = self.profile.socket + ".lock"
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode):
                raise RuntimeError("Flippy's instance lock is not owned by this user")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.fd = fd
            self._remove_stale_socket()
        except BaseException:
            self.fd = None
            os.close(fd)
            raise
        atexit.register(self.close)
        return self

    def _remove_stale_socket(self):
        path = self.profile.socket
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return
        if info.st_uid != os.getuid() or not stat.S_ISSOCK(info.st_mode):
            raise RuntimeError("Refusing to replace a socket path not owned by Flippy")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            try:
                probe.connect(path)
            except OSError as error:
                if error.errno not in (errno.ECONNREFUSED, errno.ENOENT):
                    raise RuntimeError("Could not confirm that Flippy's socket is stale") from error
            else:
                raise RuntimeError("Flippy is already running for this profile")
        if os.path.exists(path):
            now = os.lstat(path)
            if (now.st_dev, now.st_ino) != (info.st_dev, info.st_ino):
                raise RuntimeError("Flippy's socket changed during startup")
            os.unlink(path)

    def listening(self):
        info = os.lstat(self.profile.socket)
        self.socket_identity = info.st_dev, info.st_ino

    def close(self):
        if self.fd is None:
            return
        try:
            info = os.lstat(self.profile.socket)
            if self.socket_identity == (info.st_dev, info.st_ino):
                os.unlink(self.profile.socket)
        except FileNotFoundError:
            pass
        finally:
            fd, self.fd = self.fd, None
            os.close(fd)
