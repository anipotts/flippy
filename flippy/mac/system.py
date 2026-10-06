"""macOS appearance for the "Follow macOS" theme."""
from AppKit import NSApplication, NSColor, NSColorSpace


def appearance():
    """(dark, accent rgb, background rgb) from the system settings."""
    app = NSApplication.sharedApplication()
    name = app.effectiveAppearance().bestMatchFromAppearancesWithNames_(["NSAppearanceNameAqua", "NSAppearanceNameDarkAqua"])
    dark = name == "NSAppearanceNameDarkAqua"
    c = NSColor.controlAccentColor().colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
    accent = (c.redComponent(), c.greenComponent(), c.blueComponent()) if c else (0.25, 0.6, 1.0)
    bg = (0.12, 0.12, 0.13) if dark else (0.96, 0.96, 0.97)
    return dark, accent, bg
