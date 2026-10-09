"""Scripted app actions for /act: a fixed list of jobs an app's own scripting does in one step, in the background.

Where the Accessibility API sees little (Spotify) or a job takes many clicks (a new note with text), the app's
AppleScript dictionary often does it directly: no window, no pointer. This is a fixed menu of those, never free-form
AppleScript (which can run shell commands). The user's text never becomes script source: each script is a constant
that reads its values from `on run argv`, and osascript gets the values as separate arguments.

ACTIONS maps an action name to (app name, required args, script). The tool contract is in flippy/actions.py
(BACKGROUND_CATALOG["app_action"]).
"""
import html
import subprocess

from ..actions import ActionError, RetryableActionError

TIMEOUT_S = 15

ACTIONS = {
    # Spotify: playback, and playing something by its Spotify URI. Playing a search isn't scriptable.
    "spotify.play_pause": ("Spotify", (), 'tell application "Spotify" to playpause'),
    "spotify.next": ("Spotify", (), 'tell application "Spotify" to next track'),
    "spotify.previous": ("Spotify", (), 'tell application "Spotify" to previous track'),
    "spotify.shuffle_on": ("Spotify", (), 'tell application "Spotify" to set shuffling to true'),
    "spotify.shuffle_off": ("Spotify", (), 'tell application "Spotify" to set shuffling to false'),
    "spotify.play_uri": ("Spotify", ("uri",),
                         'on run argv\n tell application "Spotify" to play track (item 1 of argv)\nend run'),
    "spotify.open_search": ("Spotify", ("query",),
                            'on run argv\n open location ("spotify:search:" & (item 1 of argv))\nend run'),
    "spotify.now_playing": ("Spotify", (), 'tell application "Spotify"\n'
                            ' if player state is stopped then return "stopped"\n'
                            ' return (name of current track) & " — " & (artist of current track) & " ("'
                            ' & (player state as string) & ")"\nend tell'),
    # Music: the user's library
    "music.play_song": ("Music", ("query",), 'on run argv\n tell application "Music"\n'
                        '  set hits to (every track of library playlist 1 whose name contains (item 1 of argv)'
                        ' or artist contains (item 1 of argv))\n'
                        '  if hits is {} then return "no song in the library matches"\n'
                        '  play item 1 of hits\n'
                        '  return (name of item 1 of hits) & " — " & (artist of item 1 of hits)\n'
                        ' end tell\nend run'),
    "music.play_pause": ("Music", (), 'tell application "Music" to playpause'),
    "music.next": ("Music", (), 'tell application "Music" to next track'),
    # Notes: a new note in the default folder
    "notes.new_note": ("Notes", ("title", "body"), 'on run argv\n tell application "Notes" to make new note'
                       ' with properties {name:(item 1 of argv), body:(item 2 of argv)}\n return "created"\nend run'),
    # Mail: a draft only, shown to the user; Flippy never sends mail
    "mail.new_draft": ("Mail", ("to", "subject", "body"), 'on run argv\n tell application "Mail"\n'
                       '  set m to make new outgoing message with properties {subject:(item 2 of argv),'
                       ' content:(item 3 of argv), visible:true}\n'
                       '  if (item 1 of argv) is not "" then tell m to make new to recipient at end of to recipients'
                       ' with properties {address:(item 1 of argv)}\n'
                       ' end tell\n return "draft open, not sent"\nend run'),
    # Safari
    "safari.open_url": ("Safari", ("url",), 'on run argv\n tell application "Safari"\n'
                        '  make new document with properties {URL:(item 1 of argv)}\n end tell\nend run'),
}


def app_for(action):
    return ACTIONS[action][0] if action in ACTIONS else None


def _check(action, values):
    if action == "spotify.play_uri" and not values["uri"].startswith("spotify:"):
        raise RetryableActionError("Spotify URIs start with spotify: (spotify:track:..., spotify:playlist:...).")
    if action == "safari.open_url" and not values["url"].startswith(("https://", "http://")):
        raise RetryableActionError("Only http(s) addresses can be opened.")
    if action == "spotify.open_search":
        values["query"] = values["query"].replace(" ", "+")


def run(action, args):
    """Run one scripted action; returns what it reported (a short string)."""
    if action not in ACTIONS:
        raise RetryableActionError(f"No scripted action {action!r}. Choices: {', '.join(sorted(ACTIONS))}")
    app, needed, script = ACTIONS[action]
    values = {k: str(args.get(k, "")) for k in needed}
    missing = [k for k in needed if not values[k] and not (action == "mail.new_draft" and k == "to")]
    if missing:
        raise RetryableActionError(f"{action} needs {', '.join(missing)}.")
    _check(action, values)
    if action == "notes.new_note":  # Notes bodies are HTML: the user's text stays text
        values["body"] = "<div>" + "</div><div>".join(html.escape(line) or "<br>"
                                                       for line in values["body"].split("\n")) + "</div>"
    try:
        r = subprocess.run(["/usr/bin/osascript", "-", *[values[k] for k in needed]], input=script,
                           capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise RetryableActionError(f"{app} didn't answer in time. Try again or use its controls.") from None
    if r.returncode != 0:
        err = r.stderr.strip()
        if "-1743" in err or "Not authorized" in err:
            raise ActionError(f"Flippy isn't allowed to control {app}. Allow it in System Settings > Privacy & "
                              "Security > Automation, then try again.")
        raise RetryableActionError(f"{app} couldn't do {action} (" + (err.splitlines()[-1][:120] if err else "error")
                                   + "). Try its controls instead.")
    return r.stdout.strip() or "done"
