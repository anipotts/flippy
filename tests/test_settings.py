"""Settings migration (flippy/settings.py)."""
import unittest

from flippy import settings


class TestMigrate(unittest.TestCase):
    def test_v1_theme_names(self):
        self.assertEqual(settings._migrate({"look": {"theme": "glass"}})["look"]["theme"], "mediaplayer")
        self.assertEqual(settings._migrate({"look": {"theme": "nowplaying"}})["look"]["theme"], "glass")
        self.assertEqual(settings._migrate({"look": {"theme": "y2k"}})["look"]["theme"], "y2k")

    def test_v1_shine_setting_moves(self):
        look = settings._migrate({"look": {"glass_shine": "none"}})["look"]
        self.assertEqual(look, {"player_shine": "none"})

    def test_v2_files_are_left_alone(self):
        self.assertEqual(settings._migrate({"version": 2, "look": {"theme": "glass"}})["look"]["theme"], "glass")


if __name__ == "__main__":
    unittest.main()
