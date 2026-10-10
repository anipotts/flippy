"""Updates (flippy/updates.py): version comparison, repo detection, and a real fast-forward in a scratch repo."""
import os
import subprocess
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

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


def published(archive, version="0.2.2", digest=None):
    """The latest-release record GitHub would return for `archive`, with the sha256 it records on upload."""
    import hashlib
    name = os.path.basename(archive)
    with open(archive, "rb") as f:
        digest = digest or "sha256:" + hashlib.sha256(f.read()).hexdigest()
    return {"version": version, "assets": {name: "https://example/" + name}, "digests": {name: digest}}


def serve(archive):
    return mock.patch.object(updates, "_download", lambda url, dest: __import__("shutil").copy(archive, dest))


class TestPackageInstall(unittest.TestCase):
    """A release download (no .git) updates from its platform's file on the latest release."""

    runtime_platform = "darwin"

    def setUp(self):
        import tarfile
        # Patch this module's platform view, not global sys.platform. Both release
        # formats exercise their real requirements selection on either CI host.
        platform_patch = mock.patch.object(updates, "sys", SimpleNamespace(platform=self.runtime_platform))
        platform_patch.start()
        self.addCleanup(platform_patch.stop)
        self.platform = updates.platform_name()
        self.requirements = updates.requirements_file()
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name
        old = package(self.base, f"flippy-0.2.1-{self.platform}", self.platform,
                      {"VERSION": "0.2.1\n", "flippy/gone.py": "x\n", self.requirements: "a\n"})
        with tarfile.open(old) as tar:
            tar.extractall(self.base)
        self.root = os.path.join(self.base, f"flippy-0.2.1-{self.platform}")
        os.makedirs(os.path.join(self.root, ".venv"))
        open(os.path.join(self.root, ".venv", "keep"), "w").write("mine")

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, new, rel=None):
        with mock.patch.object(updates, "latest_release", return_value=rel or published(new)), serve(new), \
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stderr="")) as run:
            return updates.install(root=self.root, log=lambda *a: None), run

    def test_updates_from_the_release(self):
        self.assertIsNone(updates.blocked(self.root))
        new = package(self.base, f"flippy-0.2.2-{self.platform}", self.platform,
                      {"VERSION": "0.2.2\n", "flippy/video.py": "v\n", self.requirements: "a\nb\n"})
        res, run = self.install(new)
        self.assertEqual((res["from"], res["to"], res["packages"]), ("0.2.1", "0.2.2", True))
        self.assertEqual(updates.current_version_at(self.root), "0.2.2")
        self.assertTrue(os.path.exists(os.path.join(self.root, "flippy", "video.py")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "flippy", "gone.py")))  # dropped by the new version
        self.assertEqual(open(os.path.join(self.root, ".venv", "keep")).read(), "mine")  # left alone
        self.assertTrue(run.called)  # pip, for the changed requirements
        self.assertIn(os.path.join(self.root, self.requirements), run.call_args.args[0])

    def test_wrong_platform_is_refused(self):
        other_platform = "linux" if self.platform == "macos" else "macos"
        new = package(self.base, f"flippy-0.2.2-{other_platform}", other_platform, {"VERSION": "0.2.2\n"})
        rel = published(new)
        name = f"flippy-0.2.2-{self.platform}.tar.gz"  # served under this platform's name
        rel["assets"], rel["digests"] = {name: "https://example/x"}, {name: rel["digests"].popitem()[1]}
        with self.assertRaisesRegex(updates.UpdateError, "is for"):
            self.install(new, rel)
        self.assertEqual(updates.current_version_at(self.root), "0.2.1")

    def test_a_download_that_doesnt_match_the_release_is_refused(self):
        new = package(self.base, f"flippy-0.2.2-{self.platform}", self.platform,
                      {"VERSION": "0.2.2\n", "flippy/video.py": "v\n"})
        for digest, why in (("sha256:" + "0" * 64, "doesn't match"), ("", "doesn't say")):
            rel = published(new, digest=digest or None)
            if not digest:
                rel["digests"] = {}
            with self.subTest(why), self.assertRaisesRegex(updates.UpdateError, why):
                self.install(new, rel)
            self.assertEqual(updates.current_version_at(self.root), "0.2.1")
            self.assertFalse(os.path.exists(os.path.join(self.root, "flippy", "video.py")))

    def test_up_to_date(self):
        with mock.patch.object(updates, "latest_release", return_value={"version": "0.2.1", "assets": {}}):
            res = updates.install(root=self.root, log=lambda *a: None)
        self.assertEqual(res["from"], res["to"])


class TestLinuxPackageInstall(TestPackageInstall):
    runtime_platform = "linux"


RUNTIME = {"requirements-mac.txt": "a\n", "packaging/macos/Launcher.swift": "// launcher\n",
           "packaging/macos/runtime.env": "PY_VERSION=3.13.15\n"}


class TestBundledInstall(unittest.TestCase):
    """The self-contained Flippy.app: an update becomes a new copy of the code next to the running one
    (flippy/bundle.py), and only when it needs the runtime the app has."""

    def setUp(self):
        from flippy import bundle
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = self.tmp.name
        self.home = os.path.join(self.base, "Application Support", "Flippy")
        # what the launcher sets up: the running copy, current, checked against this app's runtime
        old = package(self.base, "flippy-0.2.1-macos", "macos", {"VERSION": "0.2.1\n", **RUNTIME})
        self.running = os.path.join(self.home, "versions", "1-0.2.1")
        os.makedirs(os.path.dirname(self.running))
        updates._extract(old, os.path.join(self.base, "x"))
        os.rename(os.path.join(self.base, "x", "flippy-0.2.1-macos"), self.running)
        self.runtime = bundle.runtime_id(self.running)
        os.symlink("versions/1-0.2.1", os.path.join(self.home, "code"))
        env = {"FLIPPY_BUNDLED": "1", "FLIPPY_CODE_HOME": self.home, "FLIPPY_RUNTIME": self.runtime}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        self.snapshot = self.tree(self.running)

    def tree(self, root):
        out = {}
        for d, _, names in os.walk(root):
            for n in names:
                with open(os.path.join(d, n)) as f:
                    out[os.path.relpath(os.path.join(d, n), root)] = f.read()
        return out

    def install(self, files, version="0.2.2"):
        new = package(self.base, f"flippy-{version}-macos", "macos", {"VERSION": version + "\n", **files})
        with mock.patch.object(updates, "latest_release", return_value=published(new, version)), serve(new), \
                mock.patch("subprocess.run") as run:
            res = updates.install(root=self.running, log=lambda *a: None)
        self.assertFalse(run.called)  # never pip, never ./install.sh
        return res

    def current(self):
        return os.path.realpath(os.path.join(self.home, "code"))

    def test_a_release_on_the_same_runtime_becomes_a_new_current_copy(self):
        res = self.install({**RUNTIME, "flippy/video.py": "v\n", "packaging/macos/make_icon.py": "new icon\n"})
        self.assertEqual((res["from"], res["to"], res["version"], res["packages"], res["app"]),
                         ("0.2.1", "0.2.2", "0.2.2", False, False))  # app: an icon change never runs ./install.sh
        new = self.current()
        self.assertNotEqual(new, os.path.realpath(self.running))
        self.assertEqual(updates.current_version_at(new), "0.2.2")
        self.assertTrue(os.path.exists(os.path.join(new, "flippy", "video.py")))
        self.assertEqual(open(os.path.join(new, "RUNTIME")).read().strip(), self.runtime)
        self.assertEqual(self.tree(self.running), self.snapshot)  # the running copy is untouched
        self.assertEqual(os.readlink(os.path.join(self.home, "code")),
                         os.path.join("versions", os.path.basename(new)))  # relative: the folder can move

    def test_a_release_that_needs_a_different_runtime_asks_for_the_new_app(self):
        for rel, text in (("requirements-mac.txt", "a\nb\n"), ("packaging/macos/Launcher.swift", "// v2\n"),
                          ("packaging/macos/runtime.env", "PY_VERSION=3.14.0\n")):
            with self.subTest(rel), self.assertRaisesRegex(updates.UpdateError, "Flippy.dmg"):
                self.install({**RUNTIME, rel: text, "flippy/video.py": "v\n"})
            self.assertEqual(self.current(), os.path.realpath(self.running))  # nothing switched
            self.assertEqual(self.tree(self.running), self.snapshot)
            self.assertEqual(os.listdir(os.path.join(self.home, "versions")), ["1-0.2.1"])  # nothing left behind

    def test_an_app_whose_launcher_predates_runtimes_asks_for_the_new_app(self):
        del os.environ["FLIPPY_RUNTIME"]
        with self.assertRaisesRegex(updates.UpdateError, "Flippy.dmg"):
            self.install({**RUNTIME})
        self.assertEqual(self.current(), os.path.realpath(self.running))
