"""Which shortcuts won't work (flippy/shortcuts.py): macOS clashes and COSMIC's shortcut files."""
import os
import plistlib
import tempfile
import unittest

from flippy import shortcuts

CMD, SHIFT, OPTION, CTRL = 1 << 8, 1 << 9, 1 << 11, 1 << 12  # Carbon bits, as flippy/mac/hotkeys.MODS
KEYS = {"space": 49, "v": 9, "4": 21, "k": 40}


def parse(combo):  # hotkeys.parse without Carbon
    *mods, key = combo.split("+")
    if key not in KEYS:
        raise ValueError(f"unknown key {key!r}")
    return KEYS[key], sum({"cmd": CMD, "shift": SHIFT, "option": OPTION, "ctrl": CTRL}[m] for m in mods)


class Mac(unittest.TestCase):
    def system(self, table):
        with tempfile.NamedTemporaryFile(suffix=".plist", delete=False) as f:
            plistlib.dump({"AppleSymbolicHotKeys": table}, f)
        self.addCleanup(os.unlink, f.name)
        return shortcuts.system_shortcuts(f.name)

    def test_macos_shortcuts_on_the_same_keys(self):
        system = self.system({"60": {"enabled": True, "value": {"parameters": [32, 49, 262144]}},
                              "61": {"enabled": False, "value": {"parameters": [32, 49, 786432]}}})
        self.assertEqual(shortcuts.mac_problem("ctrl+space", parse, system=system),
                         "macOS uses it for Previous input source")
        self.assertIsNone(shortcuts.mac_problem("ctrl+option+space", parse, system=system))  # turned off
        self.assertEqual(shortcuts.mac_problem("cmd+space", parse, system=system), "macOS uses it for Spotlight")
        self.assertEqual(shortcuts.mac_problem("shift+cmd+4", parse, system=system),
                         "macOS uses it for Screenshot of an area")
        self.assertIsNone(shortcuts.mac_problem("cmd+shift+space", parse, system=system))

    def test_a_turned_off_default_is_free(self):
        system = self.system({"64": {"enabled": False, "value": {"parameters": [32, 49, 1048576]}}})
        self.assertIsNone(shortcuts.mac_problem("cmd+space", parse, system=system))

    def test_apps_combos_registration_errors_and_bad_combos(self):
        self.assertEqual(shortcuts.mac_problem("shift+cmd+v", parse, system={}),
                         "it's Paste and Match Style in many apps")
        self.assertEqual(shortcuts.mac_problem("cmd+k", parse, "cmd+k is taken by another app (error -9878)", {}),
                         "cmd+k is taken by another app (error -9878)")
        self.assertIn("unknown key", shortcuts.mac_problem("cmd+zz", parse, system={}))

    def test_missing_plist_still_knows_spotlight(self):
        self.assertEqual(shortcuts.system_shortcuts("/nonexistent")[(49, 1 << 20)], "Spotlight")


CUSTOM = """{
    (
        modifiers: [
            Super,
            Shift,
        ],
        key: "space",
    ): Spawn("/home/k/.local/bin/flippy-ask"),
    (
        modifiers: [
            Super,
            Alt,
        ],
    ): Spawn("/home/k/.local/bin/flippy-ask draw"),
    (
        modifiers: [
            Super,
        ],
        key: "p",
    ): Spawn("/home/k/.local/bin/flippy-ask pause-toggle"),
    (
        modifiers: [
            Super,
            Alt,
        ],
    ): Spawn("obs --startrecording"),
}
"""
DEFAULTS = """{
    (modifiers: [Super], key: "p"): System(DisplaySettings),
    (modifiers: [Super, Shift], key: "space"): Disable,
    (modifiers: [Super], key: "slash"): System(Launcher),
}
"""


class Cosmic(unittest.TestCase):
    def test_bindings_parse_both_layouts(self):
        found = shortcuts.cosmic_bindings(CUSTOM + DEFAULTS)
        self.assertIn((frozenset({"super", "shift"}), "space", 'Spawn("/home/k/.local/bin/flippy-ask")'), found)
        self.assertIn((frozenset({"super"}), "p", "System(DisplaySettings)"), found)

    def test_unbound_and_clashing(self):
        problems = shortcuts.cosmic_problems(CUSTOM, [DEFAULTS])
        self.assertIsNone(problems["ask"])                       # Disable doesn't count
        self.assertEqual(problems["draw"], "it's also the shortcut that runs obs --startrecording")
        self.assertEqual(problems["pause"], "it's also COSMIC's display settings shortcut")
        self.assertEqual(problems["video"], "it isn't set up yet")

    def test_no_files(self):
        self.assertEqual(shortcuts.cosmic_problems("", []), {n: "it isn't set up yet" for n in shortcuts.NAMES})


if __name__ == "__main__":
    unittest.main()
