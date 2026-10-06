# Help mode on Linux (COSMIC): porting notes

Help mode watches an app you're learning and, when you seem stuck, offers a
"Need a hand?" card with **Help** / **Not now** / **Don't ask in <app>**. It's
deterministic: nothing is sent to Claude until you press Help. It currently runs
on macOS only. These notes cover how it's built there and how to bring it to
COSMIC. The short answer: **yes, it's doable on COSMIC**, with one signal
(input event counts) replaced by a close substitute.

## How it's built

The rules are platform-neutral and already shared:

| Piece | File | Platform? |
|---|---|---|
| Rules: stalled, circles, dialog, cooldown, per-app backoff, mute | `flippy/watch.py` | shared, tested (`python -m unittest discover tests`) |
| Loop: sample every 2 s on a worker thread, feed the rules, show the card, Help → normal ask | `flippy/daemon.py` (`_watch_tick`, `_watch_feed`, `_nudge_*`) | shared |
| Settings: `help.mode` (off/quiet), `help.apps`, `help.muted` | `flippy/settings.py` | shared |
| Signals | `flippy/mac/sensors.py` | **per platform** |
| The card | `flippy/mac/nudge.py` | **per platform** |
| "Watch this app" / on-off menu items | `flippy/mac/ui.py` (`refresh_help_menu`) | **per platform** |

The controller turns help mode on only if the platform object has a `sample`
method (`hasattr(self.ui, "sample")`). On Linux today it doesn't, so help mode
stays off there. To port it, give `flippy/linux/ui.py`'s `Platform` these four
methods:

```python
def sample(self) -> watch.Sample        # called on a worker thread every 2 s
def show_nudge(self, offer, on_help, on_later, on_mute)   # main thread
def hide_nudge(self)
def nudge_visible(self) -> bool
```

### What `sample()` returns

`watch.Sample(t, app, app_name, idle_s, events, thumb, windows)`. Any field you
can't provide can be `None`, and the rules that need it switch off:

| Field | Used by | macOS source |
|---|---|---|
| `app`, `app_name` | everything (only watched apps count) | `NSWorkspace.frontmostApplication()` bundle id / name |
| `idle_s` | stalled | `CGEventSourceSecondsSinceLastEventType` |
| `events` (cumulative count) | stalled ("were they busy?"), circles | `CGEventSourceCounterForEventType`: counts events without seeing them |
| `thumb` (64×40 grayscale, 0–1) | stalled ("is the screen still?"), circles | `CGDisplayCreateImage`, menu bar cropped off, drawn into a tiny gray bitmap |
| `windows` (`[(id, (x, y, w, h))]` of the front app) | dialog | `CGWindowListCopyWindowInfo` |

Return `Sample(t, None)` when Flippy's own window is in front.

## COSMIC, signal by signal

Wayland deliberately hides other apps' windows and input from ordinary clients,
so each signal goes through a protocol or portal instead. Check what your
cosmic-comp version advertises with `wayland-info`.

**Frontmost app (`app`, `app_name`)**: use the toplevel-info protocols COSMIC
exposes to clients (`ext-foreign-toplevel-list-v1` for the list with `app_id` and
`title`, plus COSMIC's `zcosmic_toplevel_info_v1` from cosmic-protocols for the
`activated` state). cosmic-panel and the dock use these. From Python, use
`pywayland` with the protocol XML, on a separate Wayland connection in a thread
so it can't disturb GTK's. `app_id` is the desktop id (e.g. `io.lmms.LMMS`),
which is what goes in `help.apps`.

**Idle time (`idle_s`)**: `ext-idle-notify-v1` sends `idled` after N ms without
input and `resumed` when input comes back. It doesn't give continuous seconds,
so register one notification with a short timeout (~2 s) and track
`last_input = time of last "resumed"`; then `idle_s = now - last_input` while
idled, else 0. Older setups may expose the same through
`org.freedesktop.ScreenSaver.GetSessionIdleTime`, but don't rely on it on COSMIC.

**Input event count (`events`)**: no Wayland equivalent: unprivileged clients
can't count global input, and reading `/dev/input` would need the `input` group,
which isn't worth it. **Substitute:** count `resumed` events from the 2 s idle
notification and add one per resume to a running total. A burst of clicking
gives several idle/resume flips, so "busy in the last minute" still works. The
thresholds in `watch.py` (`BUSY_EVENTS = 15`, `CIRCLE_MIN_EVENTS = 10`) assume
raw event counts, so lower them for Linux (e.g. 4 and 3). Add platform overrides
in `watch.py` rather than forking the rules.

**Screen thumbnail (`thumb`)**: simplest is the screenshot portal Flippy already
uses (`flippy/linux/screenshot.py`, non-interactive on COSMIC): take one, shrink
it to 64×40 grayscale with Pillow, delete the file. It writes a full PNG every
2 s, which works but is wasteful. Better options once it works:
the **ScreenCast portal** (PipeWire stream at 1 fps, with a `restore_token` so it
asks permission only once), or COSMIC's screencopy (`ext-image-copy-capture-v1`)
directly. Crop the top panel before shrinking, like macOS crops the menu bar,
or its clock will count as screen changes. **Important:** the overlay is
on screen too. The controller already pauses watching whenever Flippy shows
anything, so this only matters if you change that.

**Windows (`windows`, for the dialog rule)**: toplevel-info gives a new toplevel
with the same `app_id`, but no position or size, and `_is_dialog` needs bounds.
Options: leave `windows=None` (dialog rule off; stalled and circles still work),
or treat "a second toplevel from the focused app appeared" as a dialog by giving
it fake bounds (small, centered on the main one). Start with `None`.

## The card on COSMIC

Don't open a new layer surface for it: on COSMIC, unmapping a layer surface drops
Flippy's Wayland connection (see the top of `flippy/linux/ui.py`). A regular GTK
window can't choose its own position on Wayland, so it won't reliably land in a
corner. **Draw it in the overlay** instead, the same way the answer card's player
buttons are drawn and made clickable:

1. Add a small "nudge" layer to `OverlayBase` (`flippy/overlay.py`): text plus
   three button rects, painted in the top-right in `paint()`, with its button
   rects merged into `self.hits` (as `nudge_help`, `nudge_later`, `nudge_mute`).
   The Linux overlay already turns `self.hits` into the input region
   (`hits_changed`), so only those buttons take clicks.
2. Route those hit names from `on_control` to the three callbacks.
3. Auto-hide after `nudge.TIMEOUT_S` (15 s) with `loop.timeout_add`, counting it
   as "Not now", like `flippy/mac/nudge.py` does.

Doing it in the shared overlay means macOS could use the same themed card later
if you want them to match.

## Turning it on without a menu bar

COSMIC has no menu bar icon for Flippy, so use the CLI (and optionally the GTK
settings window):

```
flippy-ask help-mode quiet          # or off
flippy-ask watch-app io.lmms.LMMS   # toggle watching an app (its Wayland app_id)
flippy-ask demo-nudge stalled       # show the card without waiting to get stuck
```

A COSMIC shortcut running a small script could do "watch whatever's in front":
read the activated toplevel's `app_id` and call `flippy-ask watch-app`.

## Tips mode

Tips mode (`help.mode = "tips"`) is almost entirely shared and needs only one more
platform method:

| Piece | File | Platform? |
|---|---|---|
| Deck: JSON cache per app, levels, "knew that" → skip ahead, refill when low | `flippy/tips.py` (`Deck`) | shared, tested |
| Dealer: when to show one (warm-up, spacing, a short pause after activity) | `flippy/tips.py` (`Dealer`) | shared, tested |
| Writing a deck: one text-only Agent SDK `query()` with its own system prompt | `flippy/brain.py` (`write_tips`, `parse_tips`) | shared |
| Wiring: write on first watch, deal, buttons, "Show me" → normal ask | `flippy/daemon.py` (`_deck`, `_write_tips`, `_show_tip`, `set_goal`) | shared |
| The tip card | `show_tip(app_name, text, got_it, knew, show_me)` on the platform | **per platform** |

On macOS, `show_tip` reuses the "Need a hand?" panel (`Nudge.card()` in
`flippy/mac/nudge.py`) with three buttons and a 25 s timeout that counts as
"Got it". On COSMIC, draw it with the same overlay card as the help-mode nudge
(see "The card on COSMIC"): it's the same layout with different text and three
buttons instead of two. Goals: `flippy-ask goal <app_id> <text>` already works
on any platform, since it's handled by the shared controller.

The Dealer only needs `app`, `idle_s` and `events` from `sample()`. With the
idle-notify resume-count substitute for `events`, lower `CALM_BUSY_EVENTS` (10)
like the help-mode thresholds.

## Order of work

1. `sample()` with `app` + `thumb` (portal) + `idle_s` (idle-notify), `events`
   from resume counts, `windows=None`. Lower the event thresholds.
2. The overlay-drawn card and its three buttons.
3. Try it with `demo-nudge`, then for real in LMMS. Tune `STALL_S` / `AWAY_S`.
4. `show_tip` on the same overlay card, then try `help.mode = "tips"`.
5. Later: ScreenCast or screencopy instead of screenshot PNGs; dialog detection.

## Tutorials that wait for clicks

Not help mode, but the same kind of port. Steps Claude marks `:click` (`flippy/point.py`)
make playback wait until the person clicks near the pointer (`_gated`, `_on_user_click`
in `flippy/daemon.py`). The platform provides `watch_clicks(fn)` / `unwatch_clicks()`,
calling `fn(x, y)` (logical px) for left clicks in other apps. On macOS that's an
`NSEvent` global monitor, which needs no permission. Without these methods, as on Linux
today, those steps just play on a timer. On COSMIC there's no way for an ordinary client
to see clicks in other apps. Options: treat any `resumed` from idle-notify plus a screen
change as "they did it" (no position check), or give the card a clear "Done" button
and wait on that.
