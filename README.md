# Flippy

An AI tutor that sits on top of your desktop. Press a hotkey, type a question about whatever's on screen, and Claude answers in a small card, with a pointer that flies to the exact button, menu or setting it's talking about.

[![Download for macOS](https://img.shields.io/badge/Download_for-macOS_(.dmg)-111?style=for-the-badge&logo=apple&logoColor=white)](https://github.com/kap-il/flippy/releases/latest/download/Flippy.dmg)
[![Download for Linux (COSMIC)](https://img.shields.io/badge/Download_for-Linux_(.tar.gz)-e95420?style=for-the-badge&logo=linux&logoColor=white)](https://github.com/kap-il/flippy/releases/latest/download/flippy-linux.tar.gz)

Then follow [macOS](#macos) or [Linux](#linux-cosmic) below.

Runs on **macOS** (13+, native AppKit) and on **Linux with COSMIC on Wayland** (Pop!_OS 24.04). Modeled on [farzaa/clicky](https://github.com/farzaa/clicky) (macOS), rewritten from scratch in Python. If you like what I made, Farza is the pioneer! go check out (and star his repo if you starred this) [heyclicky.com](https://www.heyclicky.com/)

## What it does

- **Ask about your screen.** A hotkey opens a box; Flippy screenshots the screen, sends it to Claude with your question, and shows the answer next to a pointer on the thing it means.
- **Walkthroughs.** Multi-step answers play step by step: the pointer glides from point to point and the card follows. Pause, step back/forward, seek and change speed from the card.
- **Circle and ask.** A second hotkey lets you draw on the screen to mark something, then ask about it ("what does this say?").
- **Tutorials that wait for you.** When Claude walks you through doing something, the steps you have to do yourself wait until you click the thing (on COSMIC, Flippy infers the click from the mouse and the screen reacting; see [docs/linux-port.md](docs/linux-port.md#tutorials-that-wait-for-clicks)). If that click opens a menu or dialog Claude couldn't see yet, Flippy takes a fresh screenshot and Claude carries on from there. Next on the card skips a step. Turn it off with `timing.wait_for_clicks`.
- **Follow-ups.** Questions share one session, so "and where's bluetooth?" works. `/new` starts fresh; sessions also reset after 15 idle minutes.
- **Themes.** Midnight, Y2K Player, Media Player (a 2000s media player skin), Glass (a lock-screen style card), Terminal, and one that follows your system's accent color (macOS or COSMIC). On macOS 26+ and COSMIC Epoch 1.7+, Media Player and Glass sit on real glass.
- **Custom pointers.** Built-in hand, ring, arrow and dot, or draw your own in the 20×24 pixel editor, or import an image and pick its tip.
- **Check a video edit.** Press `⌃⌥V` on macOS or `Super+Shift+V` on COSMIC in your editor, play the edit back, press it again and ask ("is the cut at 0:12 clean?", "does the title stay up long enough?"). Flippy grabs the editor's window a few times a second, in memory only, finds the preview and the cuts, and shows Claude the frames that matter. Claude sees stills, not motion, and can't hear the audio. How it works: [docs/video-review.md](docs/video-review.md).
- **Help when you're stuck, and tips.** Flippy can watch an app you're learning and offer a hand, or a tip, at the right moment (see below).
- **Settings window** for model, effort, theme, pointer, sizes, timing, help mode and (on macOS) hotkeys.

Ordinary questions and tips stay tool-free. An explicit `/act` request can use approved desktop tools (see below). Flippy uses your existing **Claude Pro/Max subscription** through the Claude Agent SDK; no API client or key is added.

## Install

One command on either: open Terminal and paste

```bash
curl -fsSL https://raw.githubusercontent.com/kap-il/flippy/main/install.sh | bash
```

It downloads Flippy to `~/flippy` (set `FLIPPY_DIR` to put it elsewhere) and runs the right installer for your OS. Run it again any time to update. Prefer to look first? `git clone https://github.com/kap-il/flippy && cd flippy && ./install.sh` does the same.

Or download it (the buttons at the top):

- **macOS (Apple Silicon):** [Flippy.dmg](https://github.com/kap-il/flippy/releases/latest/download/Flippy.dmg). Open it and drag **Flippy** to **Applications**, then open it from Applications. Everything it needs is inside: no Homebrew or Terminal. Flippy isn't notarized, so the first time macOS says it can't verify it. Open System Settings → Privacy & Security, click **Open Anyway**, and open Flippy again. On an Intel Mac, use the one-line install above.
- **Linux:** [flippy-linux.tar.gz](https://github.com/kap-il/flippy/releases/latest/download/flippy-linux.tar.gz). Unpack it where you want Flippy to live and run `./install.sh` inside.

Each has only the code that platform needs, and updates itself from releases, like a git install does. Every release also has versioned copies (`flippy-<version>-macos.tar.gz`, `flippy-<version>-linux.tar.gz`) on the [releases page](https://github.com/kap-il/flippy/releases/latest).

### macOS

**From Flippy.dmg** (Apple Silicon): drag Flippy to Applications and open it. Nothing else to install. Its code lives in `~/Library/Application Support/Flippy/code`. An update installs the new code next to the running copy after checking it against the download's checksum, then switches over in one step, so the app itself never changes and keeps its permissions. A release that needs different packages or a different Python asks you to download the new Flippy.dmg instead.

**From the one-line install or a checkout** (any Mac): needs [Homebrew](https://brew.sh) (for cairo) and the Xcode Command Line Tools (the installer offers them if missing). `./install.sh` sets up the Python environment, builds **`~/Applications/Flippy.app`** and starts it.

Flippy lives in the menu bar (the pointer icon); there's no Dock icon. On first launch a setup window walks you through:

1. **Logging in to Claude** with your Pro/Max account (it opens Terminal running Claude Code; type `/login`).
2. **Screen Recording permission**, so Flippy can see your screen. macOS only applies it after a restart; the setup window has a button for that.
3. **Hotkeys:** `⇧⌘Space` asks, `⌃⇧Space` circles, `⌃⌥V` records a video edit to check, and double-tapping `⌘` pauses or resumes a walkthrough. Change them in Settings → Hotkeys.
4. Optionally, **open at login**.

Then a one-minute tour shows you each thing (ask, pause, skip and speed, follow along, circle, video review) and waits for you to try it, ending in Settings. Replay it from the menu (**Take the tour**) or with `flippy-ask tour`.

Reopen the setup any time from the menu bar icon → Setup…

Flippy.app is signed ad hoc (not notarized). With an install from a checkout, rebuilding it can make macOS ask for Screen Recording again. The Flippy.dmg app keeps its permissions through code updates; a new Flippy.dmg is a new build, so macOS asks once more.

### Linux (COSMIC)

Needs COSMIC on Wayland (it uses `wlr-layer-shell` through gtk4-layer-shell and the xdg-desktop-portal screenshot API) and Python 3.11+.

`./install.sh` installs the apt packages, builds gtk4-layer-shell into `~/.local` (it isn't packaged for Ubuntu/Pop!_OS 24.04), sets up the Python environment links `flippy-ask` and `flippy-daemon` into `~/.local/bin`, and adds **Flippy** to the app library (opening it shows the settings). Then:

1. **Log in to Claude:** run `claude` once and log in with your Pro/Max account. Don't set `ANTHROPIC_API_KEY`, or it would bill the API instead (the launcher unsets it to be safe).
2. **Add the hotkeys** in COSMIC Settings → Keyboard → Keyboard shortcuts → Custom shortcuts, or let `flippy-ask setup` add them for you (it also checks step 1):

| Shortcut | Command |
|---|---|
| `Super+Shift+Space` | `~/.local/bin/flippy-ask` |
| `Super+Alt` | `~/.local/bin/flippy-ask draw` |
| `Super+P` (optional) | `~/.local/bin/flippy-ask pause-toggle` |
| `Super+Shift+V` (optional) | `~/.local/bin/flippy-ask video` |

Use the full path; custom shortcuts don't always see `~/.local/bin` on `PATH`. The daemon starts itself on the first press, so there's no autostart to set up. Once it's running, Flippy's icon (your pointer) sits in the panel with the same menu as on macOS. To have it there from login (with help mode and update checks running), turn on **Open Flippy at login** in `flippy-ask setup`.

If you installed gtk4-layer-shell somewhere other than `~/.local`, set `FLIPPY_LAYER_SHELL_LIB` to its library directory.

Single monitor only for now, on both platforms. `/act` desktop tasks, the real pointer and real glass need COSMIC Epoch 1.7 or newer (`sudo apt full-upgrade` on Pop!_OS, then log in again); the first time a task needs the pointer, COSMIC asks once to allow remote desktop. The double-tap pause key can't work on Wayland, so COSMIC uses a normal shortcut. [docs/linux-port.md](docs/linux-port.md) explains how it all works there.

## Updates

Flippy checks GitHub for a new release once a day. When one is out, Flippy shows a card (**Install / Later / What's new**); **Install** updates your copy and restarts Flippy. Check any time from the menu bar or panel icon (**Check for updates…**) or with `flippy-ask update`; `flippy-ask update install` installs without asking, and `flippy-ask version` shows what you have. Turn the daily check off with `updates.check = false`. If you've edited Flippy's files yourself, it won't overwrite them: update with `git pull` instead.

Releasing (for maintainers): `scripts/release.sh 0.3 "what changed"` bumps `VERSION`, tags, pushes and publishes the GitHub Release with the macOS and Linux downloads attached. The notes' first line is what the update card shows.

## Usage

Press the ask hotkey (`⇧⌘Space` on macOS, `Super+Shift+Space` on COSMIC), type, hit Enter. `Esc` closes the box; answers fade on their own (or `flippy-ask dismiss`). Type `/new` for a fresh session or `/settings` for the settings window.

For draw mode, press the draw hotkey (`⌃⇧Space` / `Super+Alt`), drag to circle something, release, then type your question. Esc, right-click, the hotkey again, or 60 s of nothing cancels it.

### Approved desktop tasks

Put the app you want to use in front, open Flippy's question box, and type `/act <task>`, for example `/act type hello into this empty note`. Or run `flippy-ask act <task>`.

Flippy takes a screenshot, proposes a click, short text entry, shortcut, scroll or drag, and shows the exact input and its reason. Non-ASCII and control characters are escaped; proposals too long to review are refused. **Allow once** permits only that input; **Stop** or leaving the card unanswered for 60 seconds ends the task. Every completed input returns a fresh screenshot to Claude. Press the ask hotkey again or run `flippy-ask dismiss` to cancel, including while typing or dragging. Cleanup releases only input posted by Flippy before another action can start.

This uses custom tools inside the existing Agent SDK, with the same configured model, effort, and Claude login. Each task gets its own session so tools and task history don't enter ordinary tutor conversations. Screenshots and tool turns consume your subscription limits. Screen Recording and Accessibility permissions are required; allow Flippy in macOS settings and restart it if needed.

The first version supports one display, at most 12 inputs per task and 160 characters per text entry, with a five-minute task timeout. Scroll uses 1–10 native wheel lines; drag follows a straight path for 0.6 seconds within the foreground window. Before dispatch, Flippy hides its preview, checks the original target geometry and compares the screen's decoded pixels with the proposed frame. Any difference stops the task, including blinking carets or animation. During drag, intentional window movement is allowed while the app, window and display must remain the same. These checks cannot eliminate the final dispatch race. Actions can affect documents or submit forms, so review every approval. Browser interaction uses your visible desktop and session; there is no browser extension or DOM driver.

On COSMIC, tasks work through the app's controls (AT-SPI, Linux's accessibility layer) without bringing it in front. Keys it can't send that way, and clicks on spots that aren't controls, wait until you pause for a second, bring the app forward for a moment and give your window back. Terminals, settings, browsers and password managers always ask before each input. How it works: [docs/linux-port.md](docs/linux-port.md#desktop-tasks-act).

## Isolated local demo

With the normal source dependencies installed in `.venv`, run `scripts/dev.sh build`, `run`, `ask <command>`, `stop` or `doctor`. `script/build_and_run.sh --verify` builds, launches and checks the demo socket. Builds never install login items or initiate authentication.

To use the contribution as your normal app, run `scripts/dev.sh --app run`. This builds `~/Applications/Flippy.app` with the normal `dev.flippy.app` identity, configuration and hotkeys. `--app doctor` checks that profile; `--app stop` stops it only if this checkout owns the process. An existing app belonging to another checkout is never replaced. This is a local build of the contribution branch, not an upstream release.

Setup shows the exact running app and a draggable icon for adding it to macOS permission lists. Use the direct Screen Recording and Accessibility links; if a pane does not accept a drop, reveal the app in Finder and select it using the pane’s `+` button. macOS owns permission approval. Restart Flippy afterward and let its live checks confirm access.

The separate `~/Applications/Flippy Demo.app` uses `dev.flippy.demo`, `~/.config/flippy-demo`, its own socket, logs and caches. Updates and autostart are disabled. Its defaults are `⌘⌥⇧Space` to ask, `⌃⌥⇧Space` to draw, `⌃⌥⇧V` for video and double-Option to pause. Native permission prompts may appear after ad hoc signing. The normal app is not stopped or replaced.

For acceptance, `scripts/action_fixture.py` provides a disposable native window, and `tests/fixtures/desktop.html` provides a deterministic browser page. Test approval/refusal, focus and pixel changes, typing/drag cancellation and released input. Automated tests do not prove live macOS permissions or input. Release decisions are tracked in [issue #2](https://github.com/kap-il/flippy/issues/2).

For a first check, use a disposable empty TextEdit note: allow typing, verify the text, then repeat and choose **Stop**. Also try dismissing during approval and switching apps before allowing. The automated tests use fake inputs and a real in-memory MCP transport; they never operate your desktop.

Everything is also scriptable through `flippy-ask`:

```
flippy-ask                  open the question box (same as the hotkey)
flippy-ask draw             draw mode
flippy-ask video            start recording your editor; again to stop and ask (COSMIC)
flippy-ask video ask <q>    ask about the last recording without the box
flippy-ask q <question>     ask without the box
flippy-ask act <task>       approved desktop task
flippy-ask dismiss          hide the current answer
flippy-ask pause-toggle     pause or resume the walkthrough on screen
flippy-ask reset            start a fresh Claude session
flippy-ask settings         open the settings window
flippy-ask setup            open the first-run setup window
flippy-ask help-mode quiet  help mode on (or off)
flippy-ask watch-app <id>   toggle watching an app in help mode
flippy-ask demo-nudge       show the "Need a hand?" card
flippy-ask goal <id> <text> set what you want to do in an app (steers its tips)
flippy-ask demo-tip         show a tip card
flippy-ask click <x> <y>    click on screen (only with automation.clicks on)
flippy-ask preview          play a sample walkthrough with the current look
flippy-ask demo-tutorial    a sample tutorial that waits for you to click the Apple menu (the Workspaces button on COSMIC)
flippy-ask set look.theme y2k
flippy-ask quit             stop the daemon
```

## Help mode

Flippy can offer a hand when you seem stuck in an app you're learning. Turn it on from the menu bar icon (macOS) or panel icon (COSMIC): **Help when I'm stuck**, then, with the app you're learning in front, open the menu again and choose **Watch <app>**.

It watches only those apps, using simple local rules, with no Claude involved until you ask:

- **Stalled:** you were busy, then stopped for about 25 seconds while the screen stayed still. If you've been away for more than 3 minutes, it won't ask.
- **Going in circles:** the screen keeps flipping between the same few states while you click around.
- **Something popped up:** a small window appears in the middle of the app.

A small card in the top-right asks "Need a hand?". **Help** takes a screenshot and asks Claude what you're probably trying to do. **Not now** makes it wait longer in that app next time, and **Don't ask in <app>** turns it off there. Input is only counted, never read. `flippy-ask demo-nudge` shows the card without waiting. On COSMIC, see [docs/linux-port.md](docs/linux-port.md#help-mode) for where each signal comes from.

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
| `look.theme` | `midnight`, `y2k`, `mediaplayer`, `glass`, `terminal`, `cosmic` |
| `look.frosted` | `true` (default) or `false`: on COSMIC, real blur behind the Glass and Media Player panels; off, they're painted and `look.card_opacity` applies |
| `look.player_shine` | `wmp` (gloss bars) or `none`: reflections on the Media Player theme's real glass (macOS, COSMIC) |
| `look.pointer` | `theme`, `hand`, `ring`, `arrow`, `dot`, `glass` (Liquid Glass lens), `glasshand`, or `custom:<name>` |
| `look.pointer_size`, `look.text_size`, `look.card_opacity` | numbers |
| `timing.show_seconds`, `timing.max_show_seconds` | how long answers stay up |
| `timing.step_pace` | `slow`, `normal`, `fast` |
| `timing.speed` | walkthrough playback speed, `0.5`–`2.0` |
| `timing.wait_for_clicks` | `true` (default): tutorial steps wait until you click the thing |
| `help.mode` | `off`, `quiet` (offer a hand when stuck), `tips` (that, plus cached tips) |
| `help.apps`, `help.muted` | comma-separated app ids (macOS bundle ids, e.g. `com.ableton.live`; Wayland app ids on COSMIC, e.g. `io.lmms.LMMS`) |
| `automation.clicks` | `false` (default) or `true`: lets `flippy-ask click <x> <y> [double]` click on screen (macOS: needs the Accessibility permission; COSMIC: the remote desktop portal, which asks once). When on, any program running as you can make Flippy click. `/act` uses its separate per-input approval and does not enable scripted clicks. |
| `updates.check` | `true` (default): look for a new release once a day |
| `keys.pause` | `double-cmd` (default), `double-option`, `double-ctrl`, `double-shift` or `off`: pause/resume a walkthrough (macOS, needs the Accessibility permission; on COSMIC, bind `flippy-ask pause-toggle` to a shortcut) |
| `keys.ask`, `keys.draw` | macOS hotkeys, e.g. `cmd+shift+space` (modifiers: `cmd`, `ctrl`, `option`, `shift`) |

Custom pointers are stored in `~/.config/flippy/pointers/`.

Every question sends a screenshot, which uses your subscription limits faster than text-only chats.

## Troubleshooting

- **An error with a code** (like `Claude couldn't answer. · CLAUDE-FAILED`): look the code up in [docs/errors.md](docs/errors.md) for what happened and what to do.
- **Logs:** `~/Library/Logs/flippy.log` on macOS, `~/.local/state/flippy.log` on Linux.
- **Nothing happens on the hotkey:** run `~/.local/bin/flippy-ask` in a terminal to see the error. On Linux, "daemon didn't start" usually means gtk4-layer-shell isn't where `bin/flippy-daemon` looks (see `FLIPPY_LAYER_SHELL_LIB`). On macOS, another app may already own the shortcut; the log says so, and Settings → Hotkeys can change it.
- **macOS: answers say Flippy needs Screen Recording:** allow Flippy in System Settings → Privacy & Security → Screen & System Audio Recording, then restart it (menu bar icon → Setup… → Restart Flippy).
- **Pointer lands in the wrong place:** Flippy assumes one monitor; scaled (HiDPI/Retina) displays are handled, multi-monitor setups aren't yet.

## Uninstall

macOS:

```bash
flippy-ask quit
rm -rf ~/Applications/Flippy.app ~/Library/LaunchAgents/dev.flippy.app.plist ~/.local/bin/flippy-ask
rm -rf ~/.config/flippy   # settings and custom pointers, if you want them gone too
```

Linux (then remove Flippy's shortcuts in COSMIC Settings → Keyboard):

```bash
flippy-ask quit
rm -f ~/.local/bin/flippy-ask ~/.local/bin/flippy-daemon ~/.local/share/applications/dev.flippy.daemon.desktop \
      ~/.config/autostart/dev.flippy.daemon.desktop ~/.local/share/icons/hicolor/*/apps/dev.flippy.daemon.png
rm -rf ~/.config/flippy   # settings and custom pointers, if you want them gone too
```

## Project layout

```
install.sh  picks scripts/install_mac.sh or scripts/install_linux.sh
bin/        flippy-ask (CLI, talks to the daemon over a Unix socket), flippy-daemon (launcher)
flippy/     shared: daemon (controller), Claude brain, overlay painting, POINT-tag parsing, themes, settings
flippy/linux/  GTK + gtk4-layer-shell windows, portal screenshots, Wayland watcher (help mode, clicks), panel icon, settings, setup,
               /act through AT-SPI, the pointer (RemoteDesktop portal), real glass (background blur)
flippy/mac/    AppKit overlay and windows, screencapture, Carbon hotkeys, menu bar, first-run setup
packaging/macos/  Flippy.app launcher (Swift) and icon
scripts/    the macOS and Linux installers, release.sh, package.sh (the per-platform release downloads)
tests/      python -m unittest discover tests
docs/       linux-port.md: how the macOS features work on COSMIC;
            linux-0.3.0.md: instructions for bringing COSMIC up to macOS (/act, pointer input, glass, the new look);
            video-review.md: video review, and how to build it on macOS;
            errors.md: every error code Flippy shows, what it means and what to do
```

## Credits

- Pointing protocol and prompt adapted from [farzaa/clicky](https://github.com/farzaa/clicky) (MIT, Copyright (c) 2026 Farza). License text in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- [gtk4-layer-shell](https://github.com/wmww/gtk4-layer-shell) for the Linux overlay; [PyObjC](https://github.com/ronaldoussoren/pyobjc) for the macOS one.
- [VT323](https://fonts.google.com/specimen/VT323) font (SIL Open Font License, see `flippy/fonts/OFL.txt`).
