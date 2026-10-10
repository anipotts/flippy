"""The glass tint as numbers (flippy/glass.py), for platforms that paint it over a compositor's blur."""
import unittest

from flippy import glass


class Tint(unittest.TestCase):
    def test_frost_over_smoke(self):
        self.assertEqual(glass.glass_rgba(0, 0), (0.0, 0.0, 0.0, 0.0))
        r, g, b, a = glass.glass_rgba(0.03, 0.25)
        self.assertAlmostEqual(a, 0.03 + 0.25 * 0.97)
        self.assertAlmostEqual(r, 0.03 / a)  # white frost over black smoke: a light gray, mostly see-through

    def test_the_users_strength_and_color_go_on_top(self):
        clear = glass.user_tint(0.03, 0.25, strength=0, color="smoke")
        strong = glass.user_tint(0.03, 0.25, strength=1, color="smoke")
        self.assertGreater(strong[3], clear[3])
        blue = glass.user_tint(0.03, 0.25, strength=1, color="blue")
        self.assertGreater(blue[2], blue[0])

    def test_a_theme_can_bring_its_own_frost_and_smoke(self):
        self.assertNotEqual(glass.card_tint({"radius": 24, "frost": 0.06, "smoke": 0.32}),
                            glass.card_tint({"radius": 20}))


if __name__ == "__main__":
    unittest.main()
