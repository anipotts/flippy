"""Media players over MPRIS (D-Bus) on Linux: /act's media keys and Spotify's scripted actions, with no window,
pointer or focus involved (what the media keys and AppleScript do on macOS).

Gio's synchronous D-Bus calls, so they can run on the task's worker thread.
"""
from gi.repository import Gio, GLib

from ..actions import RetryableActionError

PREFIX = "org.mpris.MediaPlayer2."
PATH = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
TIMEOUT_MS = 3000
METHODS = {"play_pause": "PlayPause", "next": "Next", "previous": "Previous"}


def _bus():
    return Gio.bus_get_sync(Gio.BusType.SESSION, None)


def _call(bus, name, iface, method, args=None, reply=None):
    try:
        out = bus.call_sync(name, PATH if name != "org.freedesktop.DBus" else "/org/freedesktop/DBus", iface, method,
                            args, GLib.VariantType(reply) if reply else None, Gio.DBusCallFlags.NONE, TIMEOUT_MS,
                            None)
    except GLib.Error:
        raise RetryableActionError("The media player didn't answer. Try again, or use the app's controls.") from None
    return out.unpack() if out is not None else None


def players(bus=None):
    """Bus names of the running MPRIS players."""
    bus = bus or _bus()
    names = _call(bus, "org.freedesktop.DBus", "org.freedesktop.DBus", "ListNames", reply="(as)")[0]
    return sorted(n for n in names if n.startswith(PREFIX))


def get(name, prop, bus=None):
    bus = bus or _bus()
    return _call(bus, name, "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (PLAYER, prop)), "(v)")[0]


def choose(statuses):
    """The player the media keys mean: the one playing, else a paused one, else any. statuses: [(name, status)]."""
    for want in ("Playing", "Paused"):
        found = next((name for name, status in statuses if status == want), None)
        if found:
            return found
    return statuses[0][0] if statuses else None


def media(action):
    """play_pause / next / previous on whatever is playing."""
    bus = _bus()
    statuses = []
    for name in players(bus):
        try:
            statuses.append((name, get(name, "PlaybackStatus", bus)))
        except RetryableActionError:
            statuses.append((name, ""))
    name = choose(statuses)
    if name is None:
        raise RetryableActionError("No media player is open. Open one (use_app), then try again.")
    _call(bus, name, PLAYER, METHODS[action])


def player(app):
    """The bus name of one app's player ("spotify" -> org.mpris.MediaPlayer2.spotify, or one with an instance
    suffix), or None."""
    want = PREFIX + app
    return next((n for n in players() if n == want or n.startswith(want + ".")), None)


def call(name, method, args=None):
    _call(_bus(), name, PLAYER, method, args)


def set_property(name, prop, value):
    _call(_bus(), name, "org.freedesktop.DBus.Properties", "Set", GLib.Variant("(ssv)", (PLAYER, prop, value)))
