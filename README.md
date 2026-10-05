# Flippy

An AI tutor that sits on top of your Linux desktop. Press a hotkey, type a question about whatever's on screen, and Claude answers in a small card, with a pointer that flies to the exact button, menu or setting it's talking about.

Built for **COSMIC on Wayland** (Pop!_OS 24.04). Modeled on [farzaa/clicky](https://github.com/farzaa/clicky) (macOS), rewritten from scratch in Python + GTK4.

## What it does

- **Ask about your screen.** `Super+Shift+Space` opens a box; Flippy screenshots the screen, sends it to Claude with your question, and shows the answer next to a pointer on the thing it means.
- **Walkthroughs.** Multi-step answers play step by step: the pointer glides from point to point and the card follows. Pause, step back/forward, seek and change speed from the card.
- **Circle and ask.** `Super+Alt` lets you draw on the screen to mark something, then ask about it ("what does this say?").
- **Follow-ups.** Questions share one session, so "and where's bluetooth?" works. `/new` starts fresh; sessions also reset after 15 idle minutes.
- **Themes.** Midnight, Y2K Player, Glass, Terminal and Follow COSMIC.
- **Custom pointers.** Built-in hand, ring, arrow and dot, or draw your own in the 20×24 pixel editor, or import an image and pick its tip.
- **Settings window** for model, effort, theme, pointer, sizes and timing.

Claude only answers: it gets no tools and can't touch your files. It runs on your **Claude Pro/Max subscription** through the Claude Agent SDK, not on API credits.

## Requirements

- COSMIC desktop on Wayland (uses `wlr-layer-shell` via gtk4-layer-shell and the xdg-desktop-portal screenshot API)
- Python 3.11+
- A Claude Pro or Max subscription, logged in to Claude Code
- Single monitor (multi-monitor isn't supported yet)

## Install

### 1. System packages

```bash
sudo apt install git python3-venv python3-gi python3-gi-cairo python3-cairo python3-dbus python3-pil \
    gir1.2-gtk-4.0 gir1.2-adw-1 \
    meson ninja-build libgtk-4-dev libwayland-dev gobject-introspection libgirepository1.0-dev
```

### 2. Build gtk4-layer-shell

It isn't packaged for Ubuntu/Pop!_OS 24.04, so build it into `~/.local`:

```bash
git clone --branch v1.3.0 https://github.com/wmww/gtk4-layer-shell ~/.local/src/gtk4-layer-shell
cd ~/.local/src/gtk4-layer-shell
meson setup build --prefix ~/.local -Dexamples=false -Ddocs=false -Dtests=false -Dvapi=false
ninja -C build install
```

This puts the library in `~/.local/lib/x86_64-linux-gnu`, which `bin/flippy-daemon` preloads. If you install it somewhere else, set `FLIPPY_LAYER_SHELL_LIB` to that directory.

### 3. Get Flippy

```bash
git clone https://github.com/kap-il/flippy ~/Projects/flippy
cd ~/Projects/flippy
python3 -m venv --system-site-packages .venv   # system site-packages for PyGObject/GTK
.venv/bin/pip install claude-agent-sdk
mkdir -p ~/.local/bin
ln -s "$PWD/bin/flippy-ask" "$PWD/bin/flippy-daemon" ~/.local/bin/
```

### 4. Log in to Claude

Flippy uses your Claude Code login. If you haven't already, run `claude` once and log in with your Pro/Max account. Don't set `ANTHROPIC_API_KEY`, or it would bill the API instead (the launcher unsets it to be safe).

### 5. Add the hotkeys

COSMIC Settings → Keyboard → Keyboard shortcuts → Custom shortcuts:

| Shortcut | Command |
|---|---|
| `Super+Shift+Space` | `~/.local/bin/flippy-ask` |
| `Super+Alt` | `~/.local/bin/flippy-ask draw` |

Use the full path; custom shortcuts don't always see `~/.local/bin` on `PATH`. The daemon starts itself on the first press, so there's no autostart to set up.

## Usage

Press `Super+Shift+Space`, type, hit Enter. `Esc` closes the box; answers fade on their own (or `flippy-ask dismiss`). Type `/new` for a fresh session or `/settings` for the settings window.

For draw mode, press `Super+Alt`, drag to circle something, release, then type your question. Right-click, the hotkey again, or 60 s of nothing cancels it.

Everything is also scriptable through `flippy-ask`:

```
flippy-ask                  open the question box (same as the hotkey)
flippy-ask draw             draw mode
flippy-ask q <question>     ask without the box
flippy-ask dismiss          hide the current answer
flippy-ask reset            start a fresh Claude session
flippy-ask settings         open the settings window
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

Custom pointers are stored in `~/.config/flippy/pointers/`.

Every question sends a screenshot, which uses your subscription limits faster than text-only chats.

## Troubleshooting

- **Logs:** `~/.local/state/flippy.log`.
- **Nothing happens on the hotkey:** run `~/.local/bin/flippy-ask` in a terminal to see the error. "daemon didn't start" usually means gtk4-layer-shell isn't where `bin/flippy-daemon` looks (see `FLIPPY_LAYER_SHELL_LIB`).
- **Pointer lands in the wrong place:** Flippy assumes one monitor; scaled (HiDPI) displays are handled, multi-monitor setups aren't yet.

## Project layout

```
bin/        flippy-ask (CLI, talks to the daemon over $XDG_RUNTIME_DIR/flippy.sock), flippy-daemon (launcher)
flippy/     daemon, Claude brain, portal screenshots, POINT-tag parsing, themes, settings, pointer editor
spikes/     the original standalone experiments (overlay, screenshot, brain)
scripts/    demo recording and video editing (record_reel.py, edit_reel.py, reel_music.py, Blender scene)
```

## Credits

- Pointing protocol and prompt adapted from [farzaa/clicky](https://github.com/farzaa/clicky) (MIT).
- [gtk4-layer-shell](https://github.com/wmww/gtk4-layer-shell) for the overlay.
- [VT323](https://fonts.google.com/specimen/VT323) font (SIL Open Font License, see `flippy/fonts/OFL.txt`).
