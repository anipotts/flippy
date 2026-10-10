"""The Liquid Glass tint, as plain numbers: frost (white) over smoke (a dark shade), with the user's tint strength and
color (Settings > Look). The same formulas as flippy/mac/ui.py's glass_color / user_tint, for platforms whose glass is
a blur the compositor does and a tint Flippy paints on top (COSMIC, flippy/linux/blur.py)."""
from . import settings

FROST = {"card": 0.03}
SMOKE = {"card": 0.25}
LENS = {"frost": 0.04, "smoke": 0.06}  # the glass pointer: nearly clear
# the tint colors you can pick: deep shades, so white text reads
TINTS = {"smoke": (0, 0, 0), "blue": (0.04, 0.18, 0.62), "purple": (0.30, 0.10, 0.62), "pink": (0.66, 0.10, 0.42),
         "red": (0.66, 0.07, 0.08), "orange": (0.72, 0.30, 0.02), "green": (0.04, 0.44, 0.18)}


def glass_rgba(frost, smoke, rgb=(0, 0, 0)):
    """Frost over smoke as one (r, g, b, a): white at `frost` on top of `rgb` at `smoke`."""
    a = frost + smoke * (1 - frost)
    if not a:
        return 0.0, 0.0, 0.0, 0.0
    r, g, b = ((frost + smoke * (1 - frost) * c) / a for c in rgb)
    return r, g, b, a


def user_tint(frost, smoke, strength=None, color=None):
    """A surface's tint with the user's Glass tint strength (0-1) and color on top."""
    strength = settings.get("look", "glass_tint") if strength is None else strength
    color = settings.get("look", "glass_color") if color is None else color
    smoke += (1 - smoke) * min(max(float(strength), 0.0), 1.0) * 0.8
    return glass_rgba(frost, smoke, TINTS.get(color, TINTS["smoke"]))


def card_tint(backdrop):
    """The card's tint for a theme's backdrop ({"radius", and optionally its own "frost" and "smoke"})."""
    frost, smoke = (backdrop["frost"], backdrop["smoke"]) if "frost" in backdrop else (FROST["card"], SMOKE["card"])
    return user_tint(frost, smoke)
