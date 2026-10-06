# Bringing the macOS features to Linux (COSMIC)

Everything below exists on macOS and not yet on Linux. The shared code (Claude,
pointing, themes, settings, the controller in `flippy/daemon.py`) already works on
both; what's missing is each feature's platform piece in `flippy/linux/ui.py`. The
controller checks for those methods (`hasattr(self.ui, ...)`), so a missing piece
switches its feature off instead of crashing, and macOS-only commands answer "not
available on this platform yet".

| Feature | On Linux today | What it needs | Section |
|---|---|---|---|
| Help mode ("Need a hand?") | off | `sample()`, the nudge card | [Help mode](#help-mode) |
| Tips while you work | off | `show_tip()` (+ help mode's `sample()`) | [Tips mode](#tips-mode) |
| Tutorials wait for your click | steps play on a timer | `watch_clicks()` / `unwatch_clicks()` | [Tutorials](#tutorials-that-wait-for-clicks) |
| Update card | check + install work (`flippy-ask update`), no card | `show_update()` | [Updates](#updates) |
| Menu bar icon showing your pointer | no tray icon | a StatusNotifierItem | [Tray icon](#tray-icon) |
| Pause / resume shortcut | **works**: bind a COSMIC shortcut | nothing (docs only) | [Pause shortcut](#pause-shortcut) |
| Esc cancels draw mode | right-click / hotkey / 60 s timeout cancel | keyboard on the overlay while drawing | [Esc](#esc-cancels-draw-mode) |
| Scripted clicks (`flippy-ask click`) | no | the RemoteDesktop portal | [Scripted clicks](#scripted-clicks) |
| Real Liquid Glass (Media Player, Glass, lens, glass hand) | painted look, no blur | a compositor blur protocol | [Glass](#liquid-glass) |
| Settings window rows for the new settings | edit with `flippy-ask set` | rows in the GTK window | [Settings window](#settings-window) |
| First-run setup window | the installer prints the steps | optional | [Setup](#first-run-setup) |
| Demo tools (`shot`, `record`, `nudge`, `demo-nudge`, `demo-tip`) | no | not needed for users | [Demo tools](#demo-tools) |

# Help mode

Help mode watches an app you're learning and, when you seem stuck, offers a
"Need a hand?" card with **Help** / **Not now** / **Don't ask in <app>**. It's
deterministic: nothing is sent to Claude until you press Help. These notes cover
how it's built on macOS and how to bring it to COSMIC. The short answer: **yes,
it's doable on COSMIC**, with one signal (input event counts) replaced by a close
substitute.

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

## Updates

Checking for and installing updates (`flippy/updates.py`, `check_for_update` / `install_update`
in `flippy/daemon.py`) is shared and already works on Linux: `flippy-ask update` checks,
`flippy-ask update install` installs, and the daily check logs "update available". The one
missing piece is the card: give the Linux `Platform` a `show_update(rel, install, later)`
(the same overlay-drawn card as the help-mode nudge, with Install / Later / What's new).
`restart()` is already there.


## Tray icon

macOS shows a menu bar icon drawn from the equipped pointer, with click rays
(`flippy/mac/statusicon.py`), plus a menu (Ask, Circle, help mode, settings,
updates, quit). On COSMIC, apps get a tray icon through **StatusNotifierItem**
(the D-Bus tray protocol COSMIC's panel shows in its status area):

1. Move the drawing in `statusicon.render()` into shared code. It's plain cairo
   plus `themes`, and only `image()` is AppKit.
2. Publish an `org.kde.StatusNotifierItem` on the session bus with `dbus-python`
   (already a dependency): `IconPixmap` = the rendered ARGB32 at 22 and 44 px,
   re-sent with `NewIcon` when `look.pointer` or `look.theme` changes
   (`settings.on_change`), like `_status_icon()` in `flippy/mac/ui.py`.
3. The menu goes over `com.canonical.dbusmenu`. Mirror `MENU` in `flippy/mac/ui.py`
   and send each item to `self.command(...)`.

Template images don't exist there, so draw it white with a dark outline (or pick
from the panel's light/dark setting).

## Pause shortcut

Works today, no code needed: the `pause-toggle` command is shared. Add a COSMIC
custom shortcut (Settings → Keyboard → Custom shortcuts), for example
`Super+P` → `~/.local/bin/flippy-ask pause-toggle`. Double-tapping a bare modifier
(macOS's default, `keys.pause`) isn't possible on Wayland: apps can't watch keys
outside their own windows, and COSMIC shortcuts need a real key.

## Esc cancels draw mode

On macOS, Esc is registered as a global hotkey only while drawing
(`set_drawing_input` in `flippy/mac/ui.py`). On COSMIC the overlay is a layer
surface with `KeyboardMode.NONE`, so it never sees keys. Options:

- Switch the overlay to `KeyboardMode.EXCLUSIVE` in `set_drawing_input(True)`,
  handle Esc with a `Gtk.EventControllerKey` (calling `self.on_draw_cancel()`), and
  back to `NONE` when drawing ends. **Test this carefully:** the top of
  `flippy/linux/ui.py` notes that COSMIC kept eating keys after a layer surface's
  keyboard mode was switched back. If that still happens, don't ship it.
- Or bind a COSMIC shortcut on Esc that runs `flippy-ask draw` (the draw hotkey
  already toggles draw mode off). It would only be wanted while drawing, though,
  and COSMIC shortcuts are always on, so this is a poor fit.

Until then: right-click, the draw hotkey again, or 60 s of nothing cancels it.

## Scripted clicks

`flippy-ask click <x> <y>` (behind `automation.clicks`) posts real clicks on
macOS (`click()` in `flippy/mac/ui.py`). Wayland doesn't let apps inject input
directly; the sanctioned way is the **RemoteDesktop portal**
(`org.freedesktop.portal.RemoteDesktop`): create a session, `SelectDevices`
(pointer), `Start` (the user approves once; keep the `restore_token`), then
`NotifyPointerMotionAbsolute` + `NotifyPointerButton`. Implement it as `click()` on
the Linux `Platform`; the controller already refuses when the setting is off. It's
only needed for recording demos, so it's low priority.

## Liquid Glass

On macOS, the Media Player and Glass themes, the glass lens and the glass hand
sit on `NSGlassEffectView`: real blur and refraction of what's behind
(`has_backdrop`, `_place_glass` in `flippy/mac/ui.py`). On Linux `has_backdrop`
is False and the themes paint a stand-in (`Theme.backdrop` is ignored, and
`MediaPlayer._classic`, `Glass` and `_draw_lens` / `_draw_glass_hand` draw their
no-backdrop versions), which already looks right without blur.

For real blur, the compositor has to blur behind a region of the layer surface.
Check whether your cosmic-comp offers a background blur protocol (look for
`ext-background-effect` or a COSMIC blur protocol in `wayland-info`). If it does,
request blur for the card's rect each frame (the same rect `card_layout()` gives
`_place_glass`) and set `has_backdrop = True` on the Linux `Overlay`.

## Settings window

The GTK settings window (`flippy/linux/settings_window.py`) predates these
settings. Until it has rows for them, use `flippy-ask set`:

| Setting | Row to add (where the macOS window has it) |
|---|---|
| `help.mode` (`off` / `quiet` / `tips`) | a help section; macOS uses the menu bar instead |
| `help.apps`, `help.muted` | a list of watched apps (app ids) with remove buttons |
| `timing.wait_for_clicks` | Timing → "Wait for my clicks" |
| `look.player_shine` | Appearance → "Media Player reflections" (only matters once there's blur) |
| `updates.check` | Claude → Updates, with "Check now" running `update` |
| `automation.clicks` | only once scripted clicks exist on Linux |
| `keys.pause` | not here: on COSMIC it's a system shortcut (see above) |

The glass lens and glass hand are already in its pointer list.

## First-run setup

macOS needs a setup window because of its permissions (Screen Recording,
Accessibility) and the app bundle. On Linux, `scripts/install_linux.sh` prints the
remaining steps (Claude login, COSMIC shortcuts). A GTK assistant that checks the
Claude login (the CLI's credentials) and offers to add the shortcuts by writing
COSMIC's shortcuts file would be a nice extra, not a requirement.

## Demo tools

`flippy-ask shot`, `record`, `nudge`, `demo-nudge` and `demo-tip` exist for
recording the macOS demo. On Linux they answer "not available on this platform
yet". The Linux reel has its own recorders (`scripts/record_reel.py`,
`scripts/record_raw.py`). Nothing to port unless you want the same demo there.
