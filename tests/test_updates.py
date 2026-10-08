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


def package(base, name, platform, files):
    """A release download like scripts/package.sh makes: <name>/ with a PACKAGE file, as a .tar.gz."""
    import tarfile
    src = os.path.join(base, "src-" + name)
    for rel, text in {**files, "PACKAGE": platform + "\n", "flippy/daemon.py": "# daemon\n"}.items():
        os.makedirs(os.path.dirname(os.path.join(src, name, rel)), exist_ok=True)
        with open(os.path.join(src, name, rel), "w") as f:
            f.write(text)
    archive = os.path.join(base, name + ".tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(os.path.join(src, name), arcname=name)
    return archive


class TestPackageInstall(unittest.TestCase):
    """A release download (no .git) updates from its platform's file on the latest release."""

    def setUp(self):
        import tarfile
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name
        old = package(self.base, "flippy-0.2.1-macos", "macos",
                      {"VERSION": "0.2.1\n", "flippy/gone.py": "x\n", "requirements-mac.txt": "a\n"})
        with tarfile.open(old) as tar:
            tar.extractall(self.base)
        self.root = os.path.join(self.base, "flippy-0.2.1-macos")
        os.makedirs(os.path.join(self.root, ".venv"))
        open(os.path.join(self.root, ".venv", "keep"), "w").write("mine")

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, new):
        rel = {"version": "0.2.2", "assets": {os.path.basename(new): "https://example/" + os.path.basename(new)}}
        with mock.patch.object(updates, "latest_release", return_value=rel), \
                mock.patch.object(updates, "_download", lambda url, dest: __import__("shutil").copy(new, dest)), \
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stderr="")) as run:
            return updates.install(root=self.root, log=lambda *a: None), run

    def test_updates_from_the_release(self):
        self.assertIsNone(updates.blocked(self.root))
        new = package(self.base, "flippy-0.2.2-macos", "macos",
                      {"VERSION": "0.2.2\n", "flippy/video.py": "v\n", "requirements-mac.txt": "a\nb\n"})
        res, run = self.install(new)
        self.assertEqual((res["from"], res["to"], res["packages"]), ("0.2.1", "0.2.2", True))
        self.assertEqual(updates.current_version_at(self.root), "0.2.2")
        self.assertTrue(os.path.exists(os.path.join(self.root, "flippy", "video.py")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "flippy", "gone.py")))  # dropped by the new version
        self.assertEqual(open(os.path.join(self.root, ".venv", "keep")).read(), "mine")  # left alone
        self.assertTrue(run.called)  # pip, for the changed requirements

    def test_wrong_platform_is_refused(self):
        new = package(self.base, "flippy-0.2.2-linux", "linux", {"VERSION": "0.2.2\n"})
        rel = {"version": "0.2.2", "assets": {"flippy-0.2.2-macos.tar.gz": "https://example/x"}}
        with mock.patch.object(updates, "latest_release", return_value=rel), \
                mock.patch.object(updates, "_download", lambda url, dest: __import__("shutil").copy(new, dest)):
            with self.assertRaises(updates.UpdateError):
                updates.install(root=self.root, log=lambda *a: None)
        self.assertEqual(updates.current_version_at(self.root), "0.2.1")

    def test_up_to_date(self):
        with mock.patch.object(updates, "latest_release", return_value={"version": "0.2.1", "assets": {}}):
            res = updates.install(root=self.root, log=lambda *a: None)
        self.assertEqual(res["from"], res["to"])
