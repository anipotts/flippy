"""The self-contained Flippy.app's code layout (flippy/bundle.py), and the real launcher (packaging/macos/Launcher.swift)
compiled into a scratch app whose "Python" only reports where it was started."""
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from flippy import bundle

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = {"requirements-mac.txt": "a\n", "packaging/macos/Launcher.swift": "// launcher\n",
           "packaging/macos/runtime.env": "PY_VERSION=3.13.15\n"}


def write(root, files):
    for rel, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(root, rel)) or root, exist_ok=True)
        with open(os.path.join(root, rel), "w") as f:
            f.write(text)
    return root


def text(path):
    with open(path) as f:
        return f.read()


def release(base, version, **changes):
    return write(os.path.join(base, f"flippy-{version}"),
                 {**RUNTIME, "VERSION": version + "\n", "flippy/daemon.py": "# daemon\n", **changes})


class TestRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_only_the_runtime_files_count(self):
        a = release(os.path.join(self.tmp.name, "a"), "0.3.0")
        b = release(os.path.join(self.tmp.name, "b"), "0.3.1", **{"flippy/video.py": "new\n",
                                                                  "packaging/macos/make_icon.py": "icon\n"})
        self.assertEqual(bundle.runtime_id(a), bundle.runtime_id(b))
        for rel in bundle.RUNTIME_FILES:
            c = release(os.path.join(self.tmp.name, "c-" + rel.replace("/", "_")), "0.3.0", **{rel: "changed\n"})
            self.assertNotEqual(bundle.runtime_id(c), bundle.runtime_id(a), rel)

    def test_a_linux_release_has_no_runtime(self):
        root = release(self.tmp.name, "0.3.0")
        os.unlink(os.path.join(root, "packaging/macos/runtime.env"))
        with self.assertRaises(bundle.BundleError):
            bundle.runtime_id(root)

    def test_activate_refuses_another_runtime_and_changes_nothing(self):
        home = os.path.join(self.tmp.name, "home")
        src = release(self.tmp.name, "0.3.1", **{"requirements-mac.txt": "b\n"})
        with self.assertRaises(bundle.BundleError):
            bundle.activate(home, src, "0" * 64)
        self.assertTrue(os.path.isdir(src))
        self.assertFalse(os.path.lexists(os.path.join(home, "code")))


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("xcrun"), "the launcher is macOS-only")
class TestLauncher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.exe = os.path.join(cls.build.name, "Flippy")
        r = subprocess.run(["xcrun", "--sdk", "macosx", "swiftc", "-module-cache-path", cls.build.name + "/m",
                            "-o", cls.exe, os.path.join(ROOT, "packaging/macos/Launcher.swift")],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError("couldn't compile the launcher:\n" + r.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.realpath(self.tmp.name)  # the launcher's FlippyHome: nothing outside it is touched
        self.support = os.path.join(self.home, "Library", "Application Support", "Flippy")

    def app(self, version, runtime_files=None):
        """A Flippy.app as build_app.sh lays it out, with this version of the code."""
        app = os.path.join(self.home, f"Flippy-{version}-{len(os.listdir(self.home))}.app")
        res = os.path.join(app, "Contents", "Resources")
        code = release(os.path.join(res, "build"), version, **(runtime_files or {}))
        os.rename(code, os.path.join(res, "code"))
        runtime = bundle.runtime_id(os.path.join(res, "code"))
        write(os.path.join(res, "code"), {"RUNTIME": runtime + "\n"})
        python = write(res, {"python/bin/python3": '#!/bin/sh\nprintf "%s\\n%s\\n%s\\n" "$(pwd -P)" '
                                                     '"$FLIPPY_RUNTIME" "$FLIPPY_CODE_HOME" > "$FLIPPY_TEST_OUT"\n'})
        os.chmod(os.path.join(python, "python/bin/python3"), 0o755)
        os.makedirs(os.path.join(app, "Contents", "MacOS"))
        shutil.copy(self.exe, os.path.join(app, "Contents", "MacOS", "Flippy"))
        with open(os.path.join(app, "Contents", "Info.plist"), "wb") as f:
            plistlib.dump({"CFBundleExecutable": "Flippy", "CFBundleIdentifier": "dev.flippy.test",
                           "CFBundlePackageType": "APPL", "FlippyBundled": True, "FlippyProfile": "default",
                           "FlippyRuntime": runtime, "FlippyHome": self.home}, f)
        return app, runtime

    def launch(self, app):
        """Run the app; returns (the folder the daemon started in, FLIPPY_RUNTIME, FLIPPY_CODE_HOME)."""
        out = os.path.join(self.home, "started")
        env = {k: v for k, v in os.environ.items() if not k.startswith("FLIPPY")}
        r = subprocess.run([os.path.join(app, "Contents", "MacOS", "Flippy")], env={**env, "FLIPPY_TEST_OUT": out},
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return text(out).splitlines()

    def current(self):
        return os.path.realpath(os.path.join(self.support, "code"))

    def versions(self):
        return sorted(os.listdir(os.path.join(self.support, "versions")))

    def test_first_launch_installs_the_apps_code_and_runs_it(self):
        app, runtime = self.app("0.3.1")
        cwd, env_runtime, env_home = self.launch(app)
        self.assertEqual(cwd, self.current())
        self.assertEqual((env_runtime, env_home), (runtime, self.support))
        self.assertEqual(text(os.path.join(cwd, "VERSION")).strip(), "0.3.1")
        self.assertEqual(text(os.path.join(cwd, "RUNTIME")).strip(), runtime)
        self.assertTrue(os.path.islink(os.path.join(self.support, "code")))
        self.assertEqual(self.launch(app)[0], cwd)  # and the next launch reuses it

    def test_an_update_on_the_same_runtime_is_kept(self):
        app, runtime = self.app("0.3.1")
        first = self.launch(app)[0]
        updated = bundle.activate(self.support, release(os.path.join(self.home, "dl"), "0.3.2"), runtime)
        self.assertEqual(self.launch(app)[0], updated)  # the app's older copy doesn't replace it
        self.assertEqual(len(self.versions()), 2)
        self.assertTrue(os.path.isdir(first))  # the previous copy is kept

    def test_an_app_with_another_runtime_installs_its_own_copy_even_when_older(self):
        app, runtime = self.app("0.3.1")
        self.launch(app)
        bundle.activate(self.support, release(os.path.join(self.home, "dl"), "0.4.0"), runtime)
        old_app, old_runtime = self.app("0.3.0", {"requirements-mac.txt": "older\n"})
        cwd, env_runtime, _ = self.launch(old_app)  # e.g. an older Flippy.dmg dragged in again
        self.assertEqual(text(os.path.join(cwd, "VERSION")).strip(), "0.3.0")
        self.assertEqual(env_runtime, old_runtime)

    def test_the_first_self_contained_apps_folder_is_kept_as_the_previous_copy(self):
        legacy = write(os.path.join(self.support, "code"), {"VERSION": "0.3.0\n", "flippy/daemon.py": "#\n"})
        app, _ = self.app("0.3.0")  # same version: only the missing RUNTIME says it must be replaced
        cwd = self.launch(app)[0]
        self.assertNotEqual(cwd, legacy)
        self.assertEqual(text(os.path.join(cwd, "RUNTIME")).strip(), self.app("0.3.0")[1])
        self.assertIn("0-legacy", self.versions())

    def test_only_the_current_and_previous_copies_are_kept(self):
        app, runtime = self.app("0.3.1")
        self.launch(app)
        for v in ("0.3.2", "0.3.3", "0.3.4"):
            bundle.activate(self.support, release(os.path.join(self.home, "dl-" + v), v), runtime)
        os.makedirs(os.path.join(self.support, "versions", ".staging-9-0.3.5"))  # an interrupted install
        cwd = self.launch(app)[0]
        self.assertEqual(text(os.path.join(cwd, "VERSION")).strip(), "0.3.4")
        self.assertEqual([v.split("-", 1)[1] for v in self.versions()], ["0.3.3", "0.3.4"])


if __name__ == "__main__":
    unittest.main()
