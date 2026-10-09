# macOS features on Linux (COSMIC)

The shared code (Claude, pointing, themes, settings, help mode's rules, tips, updates,
the controller in `flippy/daemon.py`) runs on both. Each platform supplies the pieces
the controller looks for (`hasattr(self.ui, ...)`); a missing piece switches its
feature off instead of crashing, and commands that need it answer "not available on
this platform yet".

Everything COSMIC needs lives in `flippy/linux/`. The port doesn't change the shared
files or `flippy/mac/`, so macOS runs exactly what it ran before; where COSMIC needed
something of a shared file, it has its own copy or extends it from `flippy/linux/`.

**Next: Flippy 0.2.6 brings COSMIC up to macOS 0.2.5 (`/act`, real pointer input, real glass). The step-by-step instructions are in [linux-0.2.6.md](linux-0.2.6.md); the "Blocked" sections below predate COSMIC Epoch 1.7, which unblocked pointer input and blur.**

| Feature | On COSMIC | How |
|---|---|---|
| Help mode ("Need a hand?") | yes | [Help mode](#help-mode) |
| Tips while you work | yes | [Help mode](#help-mode) |
| Tutorials wait for your click | yes, inferred | [Tutorials](#tutorials-that-wait-for-clicks) |
| Update card | yes | [Cards](#the-cards) |
| Panel icon showing your pointer, with the menu | yes | [Panel icon](#panel-icon) |
| Esc cancels draw mode | yes | [Esc](#esc-cancels-draw-mode) |
| Settings rows (help mode, watched apps, wait for clicks, updates) | yes | `flippy/linux/settings_window.py` |
| First-run setup window | yes | [Setup](#first-run-setup) |
| Flippy.app (icon, open at login) | app library entry + icon, XDG autostart | `flippy/linux/desktop.py` |
| Pause / resume shortcut | a COSMIC shortcut, not a double-tap | [Pause](#pause-shortcut) |
| Demo tools `shot`, `nudge`, `demo-nudge`, `demo-tip`, `demo-update` | yes | |
| Scripted typing (`type`, `key`, `tap`) | yes | [Typing](#scripted-typing) |
| Scripted mouse (`click`, `move`, `path`) | **no** | [Blocked](#scripted-mouse) |
| Real Liquid Glass (Media Player, Glass, lens, glass hand), `look.glass_tint`, `look.glass_color`, `look.player_shine` | **no**, painted look | [Blocked](#liquid-glass) |
| `record` (demo screen recording) | yes | [Recording](#demo-recording) |
| Hotkeys set from Flippy's settings (`keys.ask`, `keys.draw`) | COSMIC owns shortcuts | [Pause](#pause-shortcut) |

## What Flippy can see on COSMIC

Wayland hides other apps' windows and input from ordinary clients. Flippy gets what it
needs from protocols cosmic-comp offers to every client, on a second, private Wayland
connection with its own thread (`flippy/linux/wl.py`). It speaks just enough of the
wire protocol itself, so there's no pywayland or generated bindings:

| Need | Protocol |
|---|---|
| The active window's app id, title and geometry, and new windows | `ext_foreign_toplevel_list_v1` + `zcosmic_toplevel_info_v1` (v2+: `get_cosmic_toplevel`) |
| Seconds since the last input | `ext_idle_notifier_v1` `get_input_idle_notification` (2 s timeout) |
| Where the mouse is, and how much it moves | an `ext_image_copy_capture` cursor session on the output |
| A tiny thumbnail of the active window, or the screen | `ext_image_copy_capture_v1` with a toplevel or output source, into a `wl_shm` buffer |

None of these ask for permission. Check what your cosmic-comp offers by listing the
registry's globals; anything missing turns the matching signal into `None`.

COSMIC's capture sessions offer `XBGR8888`/`ABGR8888` for shm, not the usual
`XRGB8888`, which is why `wl.SHM_FORMATS` tries them first.

## Help mode

`Platform.sample()` (`flippy/linux/sensors.py`) fills `watch.Sample` like macOS does:

| Field | COSMIC source |
|---|---|
| `app`, `app_name` | the activated toplevel's `app_id`; the name from its `.desktop` file |
| `idle_s` | idle-notify: 0 while busy, else seconds since input stopped |
| `events` | mouse moves (counted from the cursor session, never read) + 5 per idle → busy flip. Wayland can't count key presses, so the flips stand in for typing. The rules' thresholds stay as on macOS |
| `thumb` | the active **window** only, 64×40 grayscale: no panel clock, no Flippy overlay |
| `windows` | the app's toplevels with their geometry, so the dialog rule works too |

Flippy's own windows (`dev.flippy.daemon`) count as "nothing in front". `help.apps`
holds Wayland app ids (e.g. `io.lmms.LMMS`), which is what the panel menu's
**Watch <app>** adds.

## The cards

"Need a hand?", tips and the update card are drawn inside the overlay
(`flippy/linux/notice.py`: `NoticeLayer`, mixed in over the shared `OverlayBase`),
top-right under the panel. A separate layer surface isn't an option: unmapping one
drops Flippy's Wayland connection on COSMIC. The buttons join `self.hits`, so they're
the only clickable part.
`flippy/linux/ui.py` `Nudge` adds the timeouts (15 s "Not now", 25 s "Got it") and has
the same API as `flippy/mac/nudge.py`. macOS still uses its own panel.

## Tutorials that wait for clicks

Wayland never tells an app about clicks in other windows. `sensors.ClickWatcher`
infers them: while a step waits, it follows the mouse (cursor session) and compares a
128×72 screen thumbnail every 0.4 s with Flippy's own card and pointer blanked out
(`NoticeLayer.ink`). When the screen reacts (1% of it changed, another window became
active, a window opened, or the title changed), every spot the mouse was in the last
2 s is reported, and the controller only accepts one near the step's target. So
"clicked the right thing and something happened" moves on; a reaction elsewhere
doesn't.

Limits: a click that changes almost nothing on screen (a checkbox, a small toggle)
isn't noticed. **Next** on the card skips the step, as on macOS. `key_idle_s()` (for
"click the box and type X" steps) is any-input idle, not key-only.

## Panel icon

`flippy/linux/tray.py`: a StatusNotifierItem plus a `com.canonical.dbusmenu` menu over
dbus-python. The icon is drawn by `flippy/linux/statusicon.py` (a copy of the macOS
menu bar icon's drawing), white with a dark outline, re-sent when `look.pointer` or
`look.theme` changes. The menu mirrors macOS's: Ask, Circle, help mode, tips,
**Watch <app>**, **Set a goal for <app>…**, preview, settings, new session, updates,
setup, quit. The panel is a layer surface, so the active window while the menu is
open is still the app being learned. Left-click asks, middle-click circles where the
panel supports it.

## Esc cancels draw mode

The overlay can't take keys (switching a layer surface's keyboard mode back on COSMIC
leaves it eating keys). While drawing, `KeyCatcher` opens a 1×1 transparent regular
window that holds the keyboard; Esc cancels, and closing it hands the keyboard back,
just like the question box. COSMIC's active-window outline shows as a 2-px speck.

## First-run setup

`flippy-ask setup` (or the panel menu → Setup…) opens `flippy/linux/setup_window.py`:
it checks the Claude login (`~/.claude/.credentials.json`; **Log in…** opens a
terminal running `claude`), lists Flippy's COSMIC shortcuts, and **Add** writes the
missing ones into `~/.config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom`
(backed up to `custom.bak-flippy` first). **Open Flippy at login** writes an XDG
autostart entry, like macOS's LaunchAgent. It opens by itself when Claude isn't logged in.

## Pause shortcut

macOS's default is double-tapping ⌘ (`keys.pause`). Wayland apps can't watch keys
outside their own windows, and COSMIC shortcuts need a real key, so on COSMIC it's a
shortcut running `flippy-ask pause-toggle` (setup offers `Super+P`). For the same
reason `keys.ask` / `keys.draw` don't apply: the shortcuts live in COSMIC Settings.

## Scripted typing

`flippy-ask type/key/tap` (behind `automation.clicks`, "Let scripts type" in Settings →
Hotkeys) go through `zwp_virtual_keyboard_v1` (`flippy/linux/keyboard.py`). Like
`wtype`, each call uploads a keymap holding just the keysyms it needs, so any
character types regardless of layout. Modifiers: `ctrl`, `shift`, `alt`, `super`
(`cmd` means `super`).

## Demo recording

`flippy-ask record start <path>` / `record stop` (`flippy/linux/recorder.py`): the
ScreenCast portal (monitor, cursor embedded, persist mode 2 with its restore token in
`~/.config/flippy/screencast-token`) into `gst-launch-1.0 -e pipewiresrc ! … !
openh264enc ! h264parse ! mp4mux` (`qtmux` for .mov, `matroskamux` for .mkv). Stop
writes `<path>.json` with the wall clock, like macOS.

# Blocked on COSMIC today

## Scripted mouse

`flippy-ask click/move/path` (behind `automation.clicks`) post real mouse input
on macOS. On Wayland the sanctioned route is the RemoteDesktop portal, and
xdg-desktop-portal-cosmic doesn't implement it (it has Screenshot, ScreenCast,
FileChooser, Access, Settings). cosmic-comp also doesn't offer
`zwlr_virtual_pointer_manager_v1`, so there's no other way to move or click the
mouse. When the portal gains RemoteDesktop: session → `SelectDevices` (pointer) →
`Start` (keep the `restore_token`) → `NotifyPointerMotionAbsolute` /
`NotifyPointerButton`, as `click()`, `move()` and `path()` on the Linux `Platform`.

## Liquid Glass

The real thing needs the compositor to blur behind part of a surface. The protocol for
that, `ext-background-effect-v1`, is in wayland-protocols, but cosmic-comp doesn't
offer it yet. The themes already paint a no-backdrop look on Linux. When it shows up:
request blur for the card's rect each frame (the rect `card_layout()` gives
`_place_glass` on macOS), and the lens and glass-hand shapes, then set
`has_backdrop = True` on the Linux `Overlay`. `look.glass_tint`, `look.glass_color` and
`look.player_shine` only matter then.
