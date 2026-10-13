"""The app window's page model and bridge (flippy/shell): plain Python, no webview."""
import os
import tempfile
import unittest
from unittest import mock

from flippy import settings
from flippy.shell import bridge, schema


class ShellTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(settings, "PATH", os.path.join(self.tmp.name, "config.toml"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        settings.load()


class SchemaTest(ShellTestCase):
    def test_every_visible_setting_is_on_some_page(self):
        for plat in ("darwin", "linux"):
            shown = {f["id"] for p in schema.pages(plat) for f in p["fields"]}
            for (section, key) in settings.SETTINGS:
                if (section, key) in schema.HIDDEN:
                    self.assertNotIn(f"{section}.{key}", shown)
                    continue
                platforms = schema.LABELS.get((section, key), (None, None, None))[2]
                self.assertEqual(f"{section}.{key}" in shown, not platforms or plat in platforms, (plat, section, key))

    def test_new_settings_show_up_without_window_work(self):
        extra = dict(settings.SETTINGS)
        extra["look", "corner"] = settings.Setting("top", (("top", "Top"), ("corner", "Corner")))
        extra["history", "days"] = settings.Setting(30, (), 1, 365, 1, 0)
        defaults = {s: dict(v) for s, v in settings.DEFAULTS.items()}
        defaults["look"]["corner"] = "top"
        defaults["history"] = {"days": 30}
        with mock.patch.object(settings, "SETTINGS", extra), mock.patch.object(settings, "DEFAULTS", defaults), \
                mock.patch.object(settings, "_data", defaults):
            pages = {p["id"]: p for p in schema.pages("darwin")}
        corner = next(f for f in pages["appearance"]["fields"] if f["id"] == "look.corner")
        self.assertEqual((corner["label"], corner["control"]), ("Corner", "choice"))
        self.assertEqual(pages["history"]["fields"][0]["control"], "slider")  # a section no page claims

    def test_controls(self):
        self.assertEqual(schema.control("look", "theme"), "choice")
        self.assertEqual(schema.control("act", "infer"), "switch")
        self.assertEqual(schema.control("look", "text_size"), "slider")
        self.assertEqual(schema.control("act", "allowed_apps"), "list")
        self.assertEqual(schema.control("keys", "ask"), "shortcut")
        self.assertEqual(schema.control("help", "apps"), "text")


class BridgeTest(ShellTestCase):
    def setUp(self):
        super().setUp()
        self.pushed, self.commands = [], []
        self.b = bridge.Bridge(push=lambda e, d: self.pushed.append((e, d)), command=self.commands.append)
        self.addCleanup(self.b.close)

    def test_state(self):
        self.b.route = "settings/timing"
        r = self.b.handle({"id": 1, "op": "state"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["result"]["route"], "settings/timing")
        self.assertIn("appearance", [p["id"] for p in r["result"]["pages"]])

    def test_set_saves_validates_and_pushes(self):
        r = self.b.handle({"id": 2, "op": "set", "args": {"id": "look.text_size", "value": 18}})
        self.assertTrue(r["ok"])
        self.assertEqual(settings.get("look", "text_size"), 18)
        self.assertEqual(self.pushed[-1][0], "setting")
        self.assertEqual(self.pushed[-1][1]["value"], 18)
        bad = self.b.handle({"id": 3, "op": "set", "args": {"id": "look.text_size", "value": 999}})
        self.assertFalse(bad["ok"])
        self.assertEqual(settings.get("look", "text_size"), 18)

    def test_refuses_unknown_hidden_and_malformed(self):
        for message in [{"id": 4, "op": "set", "args": {"id": "onboarding.done", "value": True}},
                        {"id": 5, "op": "set", "args": {"id": "nope.nothing", "value": 1}},
                        {"id": 6, "op": "eval", "args": {"code": "1"}},
                        {"id": 7, "op": "_changed"},
                        {"id": 8, "op": "state", "args": ["x"]},
                        {"id": 9, "op": "set", "args": {"id": "look.theme", "value": "mono", "extra": 1}},
                        "not a dict", None]:
            self.assertFalse(self.b.handle(message)["ok"], message)
        self.assertFalse(settings.get("onboarding", "done"))

    def test_commands_are_allowlisted(self):
        self.assertTrue(self.b.handle({"id": 10, "op": "command", "args": {"name": "preview"}})["ok"])
        self.assertFalse(self.b.handle({"id": 11, "op": "command", "args": {"name": "quit"}})["ok"])
        self.assertEqual(self.commands, ["preview"])

    def test_close_stops_pushing(self):
        self.b.close()
        settings.set("look", "text_size", 20)
        self.assertEqual(self.pushed, [])


if __name__ == "__main__":
    unittest.main()
