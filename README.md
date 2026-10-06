# Flippy

An AI tutor that sits on top of your desktop. Press a hotkey, type a question about whatever's on screen, and Claude answers in a small card, with a pointer that flies to the exact button, menu or setting it's talking about.

Runs on **macOS** (13+, native AppKit) and on **Linux with COSMIC on Wayland** (Pop!_OS 24.04). Modeled on [farzaa/clicky](https://github.com/farzaa/clicky) (macOS), rewritten from scratch in Python.

## What it does

- **Ask about your screen.** A hotkey opens a box; Flippy screenshots the screen, sends it to Claude with your question, and shows the answer next to a pointer on the thing it means.
- **Walkthroughs.** Multi-step answers play step by step: the pointer glides from point to point and the card follows. Pause, step back/forward, seek and change speed from the card.
- **Circle and ask.** A second hotkey lets you draw on the screen to mark something, then ask about it ("what does this say?").
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
flippy-ask preview          play a sample walkthrough with the current look
flippy-ask set look.theme y2k
flippy-ask quit             stop the daemon
```

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

- Pointing protocol and prompt adapted from [farzaa/clicky](https://github.com/farzaa/clicky) (MIT).
- [gtk4-layer-shell](https://github.com/wmww/gtk4-layer-shell) for the Linux overlay; [PyObjC](https://github.com/ronaldoussoren/pyobjc) for the macOS one.
- [VT323](https://fonts.google.com/specimen/VT323) font (SIL Open Font License, see `flippy/fonts/OFL.txt`).
