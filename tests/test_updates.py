"""Updates (flippy/updates.py): version comparison, repo detection, and a real fast-forward in a scratch repo."""
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from flippy import updates


class TestVersions(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(updates.is_newer("0.3", "0.2"))
        self.assertTrue(updates.is_newer("v0.10", "0.9"))
        self.assertTrue(updates.is_newer("1.0", "0.9.9"))
        self.assertTrue(updates.is_newer("0.2.1", "0.2"))
        self.assertFalse(updates.is_newer("0.2", "0.2.0"))
        self.assertFalse(updates.is_newer("0.2", "0.3"))

    def test_repo_slug(self):
        for url in ("https://github.com/kap-il/flippy.git", "git@github.com:kap-il/flippy.git",
                    "https://github.com/kap-il/flippy"):
            with mock.patch("subprocess.run", return_value=mock.Mock(stdout=url + "\n")):
                self.assertEqual(updates.repo_slug(), "kap-il/flippy")


def git(root, *args):
    subprocess.run(["git", "-C", root, *args], check=True, capture_output=True)


class TestInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        self.origin, self.clone = os.path.join(base, "origin"), os.path.join(base, "clone")
        os.makedirs(self.origin)
        git(self.origin, "init", "-q", "-b", "main")
        git(self.origin, "config", "user.email", "t@t")
        git(self.origin, "config", "user.name", "t")
        open(os.path.join(self.origin, "VERSION"), "w").write("0.2\n")
        git(self.origin, "add", ".")
        git(self.origin, "commit", "-q", "-m", "0.2")
        subprocess.run(["git", "clone", "-q", self.origin, self.clone], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def release(self, files):
        for name, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(self.origin, name)) or self.origin, exist_ok=True)
            open(os.path.join(self.origin, name), "w").write(text)
        git(self.origin, "add", ".")
        git(self.origin, "commit", "-q", "-m", "next")

    def test_fast_forward(self):
        self.release({"VERSION": "0.3\n", "packaging/macos/Launcher.swift": "x"})
        res = updates.install(root=self.clone, log=lambda *a: None)
        self.assertEqual(open(os.path.join(self.clone, "VERSION")).read().strip(), "0.3")
        self.assertFalse(res["packages"])
        self.assertTrue(res["app"])

    def test_local_changes_block_it(self):
        open(os.path.join(self.clone, "VERSION"), "w").write("mine\n")
        self.release({"VERSION": "0.3\n"})
        with self.assertRaises(updates.UpdateError):
            updates.install(root=self.clone, log=lambda *a: None)
        self.assertEqual(open(os.path.join(self.clone, "VERSION")).read().strip(), "mine")  # untouched


if __name__ == "__main__":
    unittest.main()
