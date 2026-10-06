# Flippy

An AI tutor that sits on top of your desktop. Press a hotkey, type a question about whatever's on screen, and Claude answers in a small card, with a pointer that flies to the exact button, menu or setting it's talking about.

Runs on **macOS** (13+, native AppKit) and on **Linux with COSMIC on Wayland** (Pop!_OS 24.04). Modeled on [farzaa/clicky](https://github.com/farzaa/clicky) (macOS), rewritten from scratch in Python.

## What it does

- **Ask about your screen.** A hotkey opens a box; Flippy screenshots the screen, sends it to Claude with your question, and shows the answer next to a pointer on the thing it means.
- **Walkthroughs.** Multi-step answers play step by step: the pointer glides from point to point and the card follows. Pause, step back/forward, seek and change speed from the card.
- **Circle and ask.** A second hotkey lets you draw on the screen to mark something, then ask about it ("what does this say?").
- **Tutorials that wait for you.** When Claude walks you through doing something, the steps you have to do yourself wait until you click the thing (on macOS). If that click opens a menu or dialog Claude couldn't see yet, Flippy takes a fresh screenshot and Claude carries on from there. Next on the card skips a step. Turn it off with `timing.wait_for_clicks`.
- **Follow-ups.** Questions share one session, so "and where's bluetooth?" works. `/new` starts fresh; sessions also reset after 15 idle minutes.
- **Themes.** Midnight, Y2K Player, Glass, Terminal, and one that follows your system's accent color (macOS or COSMIC).
- **Custom pointers.** Built-in hand, ring, arrow and dot, or draw your own in the 20×24 pixel editor, or import an image and pick its tip.
- **Settings window** for model, effort, theme, pointer, sizes, timing and (on macOS) hotkeys.

Claude only answers: it gets no tools and can't touch your files. It runs on your **Claude Pro/Max subscription** through the Claude Agent SDK, not on API credits.

## Install

```bash
git clone https://github.com/kap-il/flippy ~/Projects/flippy
cd ~/Projects/flippy
./install.sh
```

The installer picks the right steps for your OS. Re-run it any time to update.

### macOS

Needs [Homebrew](https://brew.sh) (for cairo) and the Xcode Command Line Tools (the installer offers them if missing).

`./install.sh` sets up the Python environment, builds **`~/Applications/Flippy.app`** and starts it. Flippy lives in the menu bar (the pointer icon); there's no Dock icon. On first launch a setup window walks you through:

1. **Logging in to Claude** with your Pro/Max account (it opens Terminal running Claude Code; type `/login`).
2. **Screen Recording permission**, so Flippy can see your screen. macOS only applies it after a restart; the setup window has a button for that.
3. **Hotkeys:** `⇧⌘Space` asks, `⌃⇧Space` circles. Change them in Settings → Hotkeys.
4. Optionally, **open at login**.

Reopen the setup any time from the menu bar icon → Setup…

Flippy.app is signed ad hoc (not notarized), so rebuilding it can make macOS ask for Screen Recording again.

### Linux (COSMIC)

Needs COSMIC on Wayland (it uses `wlr-layer-shell` through gtk4-layer-shell and the xdg-desktop-portal screenshot API) and Python 3.11+.

`./install.sh` installs the apt packages, builds gtk4-layer-shell into `~/.local` (it isn't packaged for Ubuntu/Pop!_OS 24.04), sets up the Python environment and links `flippy-ask` and `flippy-daemon` into `~/.local/bin`. Then:

1. **Log in to Claude:** run `claude` once and log in with your Pro/Max account. Don't set `ANTHROPIC_API_KEY`, or it would bill the API instead (the launcher unsets it to be safe).
2. **Add the hotkeys** in COSMIC Settings → Keyboard → Keyboard shortcuts → Custom shortcuts:

| Shortcut | Command |
|---|---|
| `Super+Shift+Space` | `~/.local/bin/flippy-ask` |
| `Super+Alt` | `~/.local/bin/flippy-ask draw` |

Use the full path; custom shortcuts don't always see `~/.local/bin` on `PATH`. The daemon starts itself on the first press, so there's no autostart to set up.

If you installed gtk4-layer-shell somewhere other than `~/.local`, set `FLIPPY_LAYER_SHELL_LIB` to its library directory.

Single monitor only for now, on both platforms.

## Usage

Press the ask hotkey (`⇧⌘Space` on macOS, `Super+Shift+Space` on COSMIC), type, hit Enter. `Esc` closes the box; answers fade on their own (or `flippy-ask dismiss`). Type `/new` for a fresh session or `/settings` for the settings window.

For draw mode, press the draw hotkey (`⌃⇧Space` / `Super+Alt`), drag to circle something, release, then type your question. Right-click, the hotkey again, or 60 s of nothing cancels it.

Everything is also scriptable through `flippy-ask`:

```
flippy-ask                  open the question box (same as the hotkey)
flippy-ask draw             draw mode
flippy-ask q <question>     ask without the box
flippy-ask dismiss          hide the current answer
flippy-ask reset            start a fresh Claude session
flippy-ask settings         open the settings window
flippy-ask setup            macOS: open the first-run setup window
flippy-ask help-mode quiet  help mode on (or off)
flippy-ask watch-app <id>   toggle watching an app in help mode
flippy-ask demo-nudge       show the "Need a hand?" card
flippy-ask goal <id> <text> set what you want to do in an app (steers its tips)
flippy-ask demo-tip         show a tip card
flippy-ask click <x> <y>    click on screen (only with automation.clicks on)
flippy-ask preview          play a sample walkthrough with the current look
flippy-ask demo-tutorial    a sample tutorial that waits for you to click the Apple menu
flippy-ask set look.theme y2k
flippy-ask quit             stop the daemon
```

## Help mode (macOS)

Flippy can offer a hand when you seem stuck in an app you're learning. Turn it on from the menu bar icon: **Help when I'm stuck**, then, with the app you're learning in front, open the menu again and choose **Watch <app>**.

It watches only those apps, using simple local rules, with no Claude involved until you ask:

- **Stalled:** you were busy, then stopped for about 25 seconds while the screen stayed still. If you've been away for more than 3 minutes, it won't ask.
- **Going in circles:** the screen keeps flipping between the same few states while you click around.
- **Something popped up:** a small window appears in the middle of the app.

A small card in the top-right asks "Need a hand?". **Help** takes a screenshot and asks Claude what you're probably trying to do. **Not now** makes it wait longer in that app next time, and **Don't ask in <app>** turns it off there. Input is only counted, never read. `flippy-ask demo-nudge` shows the card without waiting. Linux support: see [docs/help-mode-linux.md](docs/help-mode-linux.md).

### Tips while you work

Turn on **Tips while I work** in the same menu, and optionally **Set a goal for <app>…** ("make a drum loop", "write a CLI in Rust"). The first time you watch an app, Flippy asks Claude once, text only, for about 25 tips, from beginner to advanced and aimed at your goal. They're saved in `~/.config/flippy/tips/`, and Flippy shows one now and then on its own: after a minute in the app, at most every 5 minutes, and only in a short pause after you've been working, never mid-flow.

- **Got it:** the next one comes later.
- **Knew that:** two of these at a level skips you to harder tips.
- **Show me:** the one live call. It takes a screenshot so Claude can point at it on your screen.

When the tips at your level run low, Flippy asks for another batch (one more text call) and tells Claude which ones you already have. Changing the goal replaces the tips you haven't seen. `flippy-ask demo-tip` shows a tip card.

## Settings

Settings live in `~/.config/flippy/config.toml`. Edit them in the settings window (`flippy-ask settings`), with `flippy-ask set <section.key> <value>`, or by hand.

| Key | Values |
|---|---|
| `claude.model` | `default`, `opus`, `sonnet`, `haiku` |
| `claude.effort` | `low`, `medium`, `high`, `max` |
| `claude.image` | screenshot size sent to Claude: `1366`, `1920`, `0` (full) |
| `look.theme` | `midnight`, `y2k`, `glass`, `terminal`, `cosmic` |
| `look.pointer` | `theme`, `hand`, `ring`, `arrow`, `dot`, or `custom:<name>` |
| `look.pointer_size`, `look.text_size`, `look.card_opacity` | numbers |
| `timing.show_seconds`, `timing.max_show_seconds` | how long answers stay up |
| `timing.step_pace` | `slow`, `normal`, `fast` |
| `timing.speed` | walkthrough playback speed, `0.5`–`2.0` |
| `timing.wait_for_clicks` | `true` (default): tutorial steps wait until you click the thing (macOS) |
| `help.mode` | `off`, `quiet` (offer a hand when stuck), `tips` (that, plus cached tips) |
| `help.apps`, `help.muted` | comma-separated app ids (macOS bundle ids, e.g. `com.ableton.live`) |
| `automation.clicks` | `false` (default) or `true`: lets `flippy-ask click <x> <y> [double]` click on screen (macOS, needs the Accessibility permission). When on, any program running as you can make Flippy click; Claude's answers never do. |
| `keys.ask`, `keys.draw` | macOS hotkeys, e.g. `cmd+shift+space` (modifiers: `cmd`, `ctrl`, `option`, `shift`) |

Custom pointers are stored in `~/.config/flippy/pointers/`.

Every question sends a screenshot, which uses your subscription limits faster than text-only chats.

## Troubleshooting

- **Logs:** `~/Library/Logs/flippy.log` on macOS, `~/.local/state/flippy.log` on Linux.
- **Nothing happens on the hotkey:** run `~/.local/bin/flippy-ask` in a terminal to see the error. On Linux, "daemon didn't start" usually means gtk4-layer-shell isn't where `bin/flippy-daemon` looks (see `FLIPPY_LAYER_SHELL_LIB`). On macOS, another app may already own the shortcut; the log says so, and Settings → Hotkeys can change it.
- **macOS: answers say Flippy needs Screen Recording:** allow Flippy in System Settings → Privacy & Security → Screen & System Audio Recording, then restart it (menu bar icon → Setup… → Restart Flippy).
- **Pointer lands in the wrong place:** Flippy assumes one monitor; scaled (HiDPI/Retina) displays are handled, multi-monitor setups aren't yet.

## Uninstall (macOS)

```bash
flippy-ask quit
rm -rf ~/Applications/Flippy.app ~/Library/LaunchAgents/dev.flippy.app.plist ~/.local/bin/flippy-ask
rm -rf ~/.config/flippy   # settings and custom pointers, if you want them gone too
```

## Project layout

```
install.sh  picks scripts/install_mac.sh or scripts/install_linux.sh
bin/        flippy-ask (CLI, talks to the daemon over a Unix socket), flippy-daemon (launcher)
flippy/     shared: daemon (controller), Claude brain, overlay painting, POINT-tag parsing, themes, settings
flippy/linux/  GTK + gtk4-layer-shell windows, portal screenshots, settings window, pointer editor
flippy/mac/    AppKit overlay and windows, screencapture, Carbon hotkeys, menu bar, first-run setup
packaging/macos/  Flippy.app launcher (Swift) and icon
spikes/     the original standalone experiments (overlay, screenshot, brain)
scripts/    demo recording and video editing (record_reel.py, edit_reel.py, reel_music.py, Blender scene)
```

## Credits

- Pointing protocol and prompt adapted from [farzaa/clicky](https://github.com/farzaa/clicky) (MIT, Copyright (c) 2026 Farza). License text in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- [gtk4-layer-shell](https://github.com/wmww/gtk4-layer-shell) for the Linux overlay; [PyObjC](https://github.com/ronaldoussoren/pyobjc) for the macOS one.
- [VT323](https://fonts.google.com/specimen/VT323) font (SIL Open Font License, see `flippy/fonts/OFL.txt`).
