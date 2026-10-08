"""Flippy as a COSMIC app: its launcher entry and icon, and opening at login (the macOS LaunchAgent's counterpart).

The entry is named after the GTK application id (dev.flippy.daemon), so COSMIC's
dock and app library show Flippy's icon for its windows. Opening it from the app
library starts Flippy if needed and shows its settings, like reopening Flippy.app.

Usage: python -m flippy.linux.desktop install   (scripts/install_linux.sh runs it)
"""
import os
import sys

APP_ID = "dev.flippy.daemon"
DATA = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
CONFIG = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
ENTRY = os.path.join(DATA, "applications", APP_ID + ".desktop")
AUTOSTART = os.path.join(CONFIG, "autostart", APP_ID + ".desktop")
ICON_SIZES = (32, 48, 64, 128, 256, 512)
ASK = os.path.expanduser("~/.local/bin/flippy-ask")


def _entry(args, extra=""):
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Flippy\n"
            "Comment=Ask about your screen; Flippy points at the answer\n"
            f"Exec={ASK} {args}\n"
            f"Icon={APP_ID}\n"
            "Categories=Utility;\n"
            "Terminal=false\n"
            f"StartupWMClass={APP_ID}\n" + extra)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def install():
    """The app library entry and the icon (the same pixel hand on a midnight tile as Flippy.app's)."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.path.join(root, "packaging", "macos"))
    from make_icon import draw
    for size in ICON_SIZES:
        path = os.path.join(DATA, "icons", "hicolor", f"{size}x{size}", "apps", APP_ID + ".png")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        draw(size).write_to_png(path)
    _write(ENTRY, _entry("settings"))


def autostart_on():
    return os.path.exists(AUTOSTART)


def set_autostart(on):
    """Start Flippy at login (its panel icon, help mode and update checks need it running)."""
    if on:
        _write(AUTOSTART, _entry("start", "NoDisplay=true\nX-GNOME-Autostart-enabled=true\n"))
    else:
        try:
            os.unlink(AUTOSTART)
        except FileNotFoundError:
            pass


if __name__ == "__main__" and sys.argv[1:] == ["install"]:
    install()
