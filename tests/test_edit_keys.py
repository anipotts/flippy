"""Editing shortcuts in the question box: macOS answers ⌘A/C/X/V/Z itself (no menu bar), COSMIC leaves them
to GTK's entry, and neither box takes any key but Return, Esc, Up and Down for itself."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).parents[1]


@unittest.skipUnless(sys.platform == "darwin", "macOS only")
class MacEditKeys(unittest.TestCase):
    def event(self, chars, *mods):
        import AppKit
        flags = 0
        for m in mods:
            flags |= {"cmd": AppKit.NSEventModifierFlagCommand, "shift": AppKit.NSEventModifierFlagShift,
                      "option": AppKit.NSEventModifierFlagOption, "ctrl": AppKit.NSEventModifierFlagControl}[m]
        return SimpleNamespace(modifierFlags=lambda: flags, charactersIgnoringModifiers=lambda: chars)

    def test_command_keys_map_to_edit_actions(self):
        from flippy.mac.ui import edit_action
        for (chars, mods), action in {("a", ("cmd",)): "selectAll:", ("c", ("cmd",)): "copy:",
                                      ("x", ("cmd",)): "cut:", ("v", ("cmd",)): "paste:",
                                      ("z", ("cmd",)): "undo:", ("Z", ("cmd", "shift")): "redo:",
                                      ("v", ("cmd", "shift", "option")): "pasteAsPlainText:"}.items():
            with self.subTest(chars=chars, mods=mods):
                self.assertEqual(edit_action(self.event(chars, *mods)), action)

    def test_other_keys_are_left_to_the_field(self):
        from flippy.mac.ui import edit_action
        for chars, mods in (("a", ()), ("a", ("ctrl",)), ("c", ("cmd", "ctrl")), ("k", ("cmd",)),
                            ("v", ("cmd", "shift"))):
            with self.subTest(chars=chars, mods=mods):
                self.assertIsNone(edit_action(self.event(chars, *mods)))


class LinuxBoxKeys(unittest.TestCase):
    def test_only_escape_up_and_down_are_taken(self):
        tree = ast.parse((ROOT / "flippy/linux/ui.py").read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "InputBox")
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_on_key")
        gdk = SimpleNamespace(KEY_Escape=0xff1b, KEY_Up=0xff52, KEY_Down=0xff54)
        ns = {"Gdk": gdk}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "<box>", "exec"), ns)
        box = SimpleNamespace(on_cancel=Mock(), recall=Mock())
        # Ctrl+A/C/V/X/Z, Ctrl+Shift+Z, Ctrl+Backspace, Home/End, Left/Right: GTK's entry handles these
        for keyval in (ord("a"), ord("c"), ord("v"), ord("x"), ord("z"), ord("Z"), 0xff08, 0xff50, 0xff57,
                       0xff51, 0xff53):
            with self.subTest(keyval=hex(keyval)):
                self.assertFalse(ns["_on_key"](box, None, keyval, 0, 0))
        self.assertTrue(ns["_on_key"](box, None, gdk.KEY_Up, 0, 0))
        box.recall.assert_called_once_with(older=True)
        self.assertTrue(ns["_on_key"](box, None, gdk.KEY_Escape, 0, 0))
        box.on_cancel.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
