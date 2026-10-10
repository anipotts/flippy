"""Linux-only pieces that run without a desktop: COSMIC shortcut writing, the click watcher's comparison,
the panel icon. Run: python -m unittest discover tests"""
import os
import sys
import tempfile
import unittest

LINUX = sys.platform.startswith("linux")


@unittest.skipUnless(LINUX, "Linux only")
class Shortcuts(unittest.TestCase):
    def test_adds_to_existing_file_and_backs_it_up(self):
        from flippy.linux import settings_window, setup_window
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "custom")
            with open(path, "w") as f:
                f.write('{\n    (\n        modifiers: [\n            Super,\n        ],\n        key: "t",\n'
                        '    ): Spawn("cosmic-term")\n}\n')  # no trailing comma on the last entry
            pause = [w[1] for w in setup_window.WANTED].index("pause-toggle")
            setup_window.add_shortcuts([0, pause], path)
            self.assertTrue(os.path.exists(path + ".bak-flippy"))
            old, settings_window.SHORTCUTS = settings_window.SHORTCUTS, path
            try:
                found = settings_window.flippy_shortcuts()
            finally:
                settings_window.SHORTCUTS = old
            self.assertEqual([args for _, args in found], ["", "pause-toggle"])
            self.assertEqual(settings_window.pretty_accel(found[0][0]), "Super+Shift+Space")
            self.assertIn('Spawn("cosmic-term"),', open(path).read())

    def test_creates_missing_file(self):
        from flippy.linux import setup_window
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "v1", "custom")
            setup_window.add_shortcuts([1], path)
            text = open(path).read()
            self.assertTrue(text.startswith("{") and text.rstrip().endswith("}"))
            self.assertIn("flippy-ask draw", text)


@unittest.skipUnless(LINUX, "Linux only")
class ClickChange(unittest.TestCase):
    def setUp(self):
        from flippy.linux import sensors
        self.s = sensors
        self.cw = sensors.ClickWatcher.__new__(sensors.ClickWatcher)
        self.cw.screen = (2560, 1440)
        self.cw.ink = lambda: [(0, 0, 640, 360)]  # Flippy's card: the top-left quarter
        self.W, self.H = sensors.CLICK_THUMB_W, sensors.CLICK_THUMB_H

    def changed(self, x0, y0, x1, y1):
        a = [0.0] * (self.W * self.H)
        b = list(a)
        for y in range(y0, y1):
            for x in range(x0, x1):
                b[y * self.W + x] = 1.0
        return self.cw._changed(a, b)

    def test_flippys_own_card_doesnt_count(self):
        self.assertEqual(self.changed(0, 0, self.W // 4, self.H // 4), 0.0)

    def test_a_menu_opening_counts(self):
        self.assertGreaterEqual(self.changed(60, 40, 80, 60), self.s.CLICK_AREA)

    def test_a_hover_highlight_doesnt(self):
        self.assertLess(self.changed(60, 40, 63, 42), self.s.CLICK_AREA)


@unittest.skipUnless(LINUX, "Linux only")
class TrayIcon(unittest.TestCase):
    def test_pixmaps(self):
        from flippy.linux import tray
        for style in ("hand", "ring", "glasshand"):
            maps = tray._pixmaps(style)
            self.assertEqual([(int(w), int(h), len(data)) for w, h, data in maps],
                             [(px, px, px * px * 4) for px in tray.ICON_PX])
            self.assertTrue(any(data[i] for data in [maps[0][2]] for i in range(0, len(data), 4)))  # some alpha


@unittest.skipUnless(LINUX, "Linux only")
class Setup(unittest.TestCase):
    """The setup window's words, worked out without a window (flippy/linux/setup_window.py)."""

    def test_the_line_under_use(self):
        from flippy.linux.setup_window import provider_prompt
        text, bright, pick = provider_prompt("auto", True, True)
        self.assertEqual(text, "Both are connected. Pick Claude or ChatGPT under Use to finish setup.")
        self.assertTrue(bright and pick)
        text, bright, pick = provider_prompt("codex", True, False)
        self.assertEqual(text, "ChatGPT isn't connected yet. Connect it above, or pick the other.")
        self.assertTrue(bright)
        self.assertFalse(pick)
        for args in (("auto", True, False), ("auto", False, False), ("claude", True, True)):
            self.assertEqual(provider_prompt(*args), ("You can switch any time in Settings → Models.", False, False))

    def test_keycaps_and_missing_shortcuts(self):
        from flippy.linux.setup_window import accel_tokens, missing_text
        self.assertEqual(accel_tokens("<Super><Shift>space"), ["Super", "Shift", "Space"])
        self.assertEqual(accel_tokens("<Super>p"), ["Super", "P"])
        self.assertEqual(missing_text([1, 3]), "Not in COSMIC yet: circle something, then ask (Super+Alt), "
                                               "pause / resume a walkthrough (Super+P).")


@unittest.skipUnless(LINUX, "Linux only")
class Eyedropper(unittest.TestCase):
    def test_the_portals_answer(self):
        from flippy.linux.screenshot import picked_color
        self.assertEqual(picked_color(0, {"color": (0.25, 1.2, -0.1)}), ((0.25, 1.0, 0.0), False))
        self.assertEqual(picked_color(1, {}), (None, False))  # they pressed Esc
        self.assertEqual(picked_color(2, {}), (None, True))   # the portal couldn't
        self.assertEqual(picked_color(0, {}), (None, True))


if __name__ == "__main__":
    unittest.main()
