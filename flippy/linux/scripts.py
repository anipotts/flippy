"""Scripted app actions for /act on Linux: the Linux side of flippy/mac/scripts.py, with the same action names where
Linux can do them, in the background (no window or pointer).

Spotify (and any player) through MPRIS over D-Bus (flippy/linux/mpris.py), searches and web addresses as URIs
handed to their app. The user's values are arguments to D-Bus calls or the URI's escaped text, never part of a
command line. Not here: music.*, notes.* and mail.* (they're scripting a macOS app's AppleScript dictionary).

ACTIONS maps an action name to (app name or None, required args). browser.open_url's app is the default browser,
looked up when it runs (app_for). The tool contract is in flippy/linux/act.py (CATALOG["app_action"]).
"""
import urllib.parse

from gi.repository import Gio, GLib

from ..actions import RetryableActionError
from . import mpris

ACTIONS = {
    "spotify.play_pause": ("Spotify", ()),
    "spotify.next": ("Spotify", ()),
    "spotify.previous": ("Spotify", ()),
    "spotify.shuffle_on": ("Spotify", ()),
    "spotify.shuffle_off": ("Spotify", ()),
    "spotify.play_uri": ("Spotify", ("uri",)),
    "spotify.open_search": ("Spotify", ("query",)),
    "spotify.now_playing": ("Spotify", ()),
    "browser.open_url": (None, ("url",)),
}
SPOTIFY_METHODS = {"spotify.play_pause": "PlayPause", "spotify.next": "Next", "spotify.previous": "Previous"}


def default_browser():
    """The default web browser's name ("Firefox"), or None."""
    info = Gio.AppInfo.get_default_for_uri_scheme("https")
    return info.get_display_name() if info else None


def app_for(action):
    """The app that has to be the task's target for this action, by its display name."""
    if action == "browser.open_url":
        return default_browser()
    return ACTIONS[action][0] if action in ACTIONS else None


def _check(action, values):
    if action == "spotify.play_uri" and not values["uri"].startswith("spotify:"):
        raise RetryableActionError("Spotify URIs start with spotify: (spotify:track:..., spotify:playlist:...).")
    if action == "browser.open_url" and not values["url"].startswith(("https://", "http://")):
        raise RetryableActionError("Only http(s) addresses can be opened.")


def _spotify():
    name = mpris.player("spotify")
    if name is None:
        raise RetryableActionError("Spotify isn't running, or its media controls aren't on. Open it (use_app "
                                   "Spotify), then try again.")
    return name


def _open_uri(uri, what):
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
    except GLib.Error:
        raise RetryableActionError(f"Nothing on this computer opens {what}. Try the app's controls instead.") from None


def run(action, args):
    """Run one scripted action; returns what it reported (a short string)."""
    if action not in ACTIONS:
        raise RetryableActionError(f"No scripted action {action!r}. Choices: {', '.join(sorted(ACTIONS))}")
    needed = ACTIONS[action][1]
    values = {k: str(args.get(k, "")) for k in needed}
    missing = [k for k in needed if not values[k]]
    if missing:
        raise RetryableActionError(f"{action} needs {', '.join(missing)}.")
    _check(action, values)
    if action == "browser.open_url":
        _open_uri(values["url"], "web addresses")
        return "opened"
    if action == "spotify.open_search":
        # Spotify handles spotify: links itself, running or not; "city pop" -> city%20pop, not city+pop
        _open_uri("spotify:search:" + urllib.parse.quote(values["query"], safe=""), "Spotify links")
        return "search open"
    name = _spotify()
    if action in SPOTIFY_METHODS:
        mpris.call(name, SPOTIFY_METHODS[action])
        return "done"
    if action == "spotify.play_uri":
        mpris.call(name, "OpenUri", GLib.Variant("(s)", (values["uri"],)))
        return "playing"
    if action in ("spotify.shuffle_on", "spotify.shuffle_off"):
        want = action == "spotify.shuffle_on"
        try:
            mpris.set_property(name, "Shuffle", GLib.Variant("b", want))
            took = mpris.get(name, "Shuffle") == want
        except RetryableActionError:
            took = False
        if not took:
            raise RetryableActionError("Spotify doesn't take shuffle through its media controls. Click its Shuffle "
                                       "button instead.")
        return "shuffle " + ("on" if want else "off")
    return now_playing(name)


def now_playing(name):
    status = mpris.get(name, "PlaybackStatus")
    if status == "Stopped":
        return "stopped"
    meta = mpris.get(name, "Metadata") or {}
    artists = meta.get("xesam:artist") or []
    title = meta.get("xesam:title") or "unknown"
    return f"{title} — {', '.join(artists) or 'unknown'} ({status.lower()})"
