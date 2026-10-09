"""Profile separation and Unix socket ownership, without launching an app."""
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from flippy.profile import Instance, Profile, current


class TestProfiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {
            "XDG_CONFIG_HOME": self.temp.name, "XDG_RUNTIME_DIR": self.temp.name,
            "XDG_STATE_HOME": self.temp.name,
        })
        self.environment.start()
        self.profile = Profile("demo")
        self.instances = []
        self.sockets = []

    def tearDown(self):
        for instance in self.instances:
            instance.close()
        for listener in self.sockets:
            listener.close()
        self.environment.stop()
        self.temp.cleanup()

    def instance(self):
        instance = Instance(self.profile)
        self.instances.append(instance)
        return instance

    def listener(self, listen=True):
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sockets.append(listener)
        listener.bind(self.profile.socket)
        if listen:
            listener.listen()
        return listener

    def test_demo_and_default_paths_are_separate(self):
        normal, demo = Profile(), self.profile
        for name in ("config_dir", "socket", "events", "log", "app", "bundle_id"):
            self.assertNotEqual(getattr(normal, name), getattr(demo, name), name)
        with patch.dict(os.environ, {"FLIPPY_PROFILE": "demo"}):
            self.assertEqual(current(), demo)
        with patch.dict(os.environ, {"FLIPPY_PROFILE": "misspelled"}):
            with self.assertRaises(ValueError):
                current()

    def test_active_unlocked_listener_is_not_unlinked(self):
        self.listener()
        before = os.lstat(self.profile.socket)
        with self.assertRaises(RuntimeError):
            self.instance().acquire()
        after = os.lstat(self.profile.socket)
        self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(self.profile.socket)

    def test_stale_owned_socket_is_removed(self):
        self.listener(listen=False).close()
        self.instance().acquire()
        self.assertFalse(os.path.lexists(self.profile.socket))

    def test_regular_file_and_symlink_are_preserved(self):
        path = Path(self.profile.socket)
        path.write_text("keep")
        with self.assertRaises(RuntimeError):
            self.instance().acquire()
        self.assertEqual(path.read_text(), "keep")
        path.unlink()
        target = Path(self.temp.name, "target")
        target.write_text("keep target")
        path.symlink_to(target)
        with self.assertRaises(RuntimeError):
            self.instance().acquire()
        self.assertTrue(path.is_symlink())
        self.assertEqual(target.read_text(), "keep target")

    def test_second_instance_cannot_acquire_and_first_lock_remains(self):
        first = self.instance().acquire()
        self.listener()
        first.listening()
        with self.assertRaises(BlockingIOError):
            self.instance().acquire()
        self.assertTrue(os.path.exists(self.profile.socket))
        first.close()
        self.assertFalse(os.path.lexists(self.profile.socket))
        self.instance().acquire()

    def test_close_does_not_remove_replacement_path(self):
        first = self.instance().acquire()
        self.listener()
        first.listening()
        replacement = Path(self.temp.name, "replacement")
        replacement.write_text("keep")
        os.replace(replacement, self.profile.socket)
        first.close()
        first.close()
        self.assertEqual(Path(self.profile.socket).read_text(), "keep")

    def test_close_without_listening_does_not_remove_path(self):
        first = self.instance().acquire()
        Path(self.profile.socket).write_text("unowned")
        first.close()
        self.assertEqual(Path(self.profile.socket).read_text(), "unowned")


if __name__ == "__main__":
    unittest.main()
