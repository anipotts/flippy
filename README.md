# Flippy

An AI tutor that sits on top of your desktop. Press a hotkey, type a question about whatever's on screen, and Claude answers in a small card, with a pointer that flies to the exact button, menu or setting it's talking about.

Runs on **macOS 13+** (Apple Silicon or Intel) and on **Linux with COSMIC on Wayland** (Pop!_OS 24.04). Modeled on [farzaa/clicky](https://github.com/farzaa/clicky) (macOS), rewritten from scratch in Python. If you like what I made, Farza is the pioneer! go check out (and star his repo if you starred this) [heyclicky.com](https://www.heyclicky.com/)

## Install

Flippy installs from source with one command. There's no `.dmg` or download to open: Flippy isn't notarized by Apple, so a downloaded app gets blocked by macOS. Building it on your own Mac avoids that.

**You need:** a Mac with macOS 13 or newer, or Linux with COSMIC (Pop!_OS 24.04); a Claude Pro or Max subscription (or ChatGPT, through Codex); about 10 minutes.

### Easiest: let Claude or ChatGPT install it for you

Not comfortable with Terminal? Let an AI coding assistant do it and talk you through the clicks.

1. Open **Claude Code** (in the [Claude desktop app](https://claude.ai/download), or type `claude` in Terminal) or **Codex** (the [ChatGPT Codex app or CLI](https://developers.openai.com/codex/cli/)).
2. Copy everything in the box below, paste it in, and press Return.
3. Do what it asks. It will tell you when to type your password, what to click, and what to try at the end.

```text
Please install Flippy for me: https://github.com/kap-il/flippy
I'm not technical, so explain each step in plain words before you do it, and tell me exactly what to click when you need me.

1. Check my computer first. Flippy needs macOS 13 or newer, or Linux with the COSMIC desktop (Pop!_OS 24.04). If it's neither, stop and tell me.
2. Read the "Install" section of that README and follow the steps for my system, using the official installer:
   curl -fsSL https://raw.githubusercontent.com/kap-il/flippy/main/install.sh | bash
3. If something it needs is missing (on a Mac: Homebrew, or the Xcode Command Line Tools), help me install it. When a step needs my password, give me the exact command to paste into Terminal myself, and remind me that the password doesn't show while I type it.
4. When the installer finishes, walk me through Flippy's setup, one step at a time:
   - connecting my Claude (or ChatGPT) account,
   - on a Mac: turning Flippy on in System Settings > Privacy & Security > Screen & System Audio Recording, and in Accessibility, then restarting Flippy from its menu bar icon (Setup… > Restart),
   - on Linux: adding the keyboard shortcuts with ~/.local/bin/flippy-ask setup.
5. Don't change anything else on my computer. Don't set ANTHROPIC_API_KEY or OPENAI_API_KEY: Flippy uses my subscription, not an API key.
6. At the end, tell me the shortcut that opens Flippy, and give me one question and one "do this for me" request to try.
```

If anything goes wrong, paste the error back into the same chat and ask it to fix it.

**Or do it yourself**, with the steps for your system below.

### macOS

1. **Install Homebrew** if you don't have it. Paste the command from [brew.sh](https://brew.sh) into Terminal and follow what it prints.
2. **Install Flippy.** Paste this into Terminal:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/kap-il/flippy/main/install.sh | bash
   ```

   If macOS asks to install the Xcode Command Line Tools, click **Install**, wait for it to finish, then paste the command again. The first run downloads about 200 MB and takes a few minutes.
3. **Wait for the setup window.** Flippy builds `~/Applications/Flippy.app` and opens it. It lives in the menu bar (the pointer icon), with no Dock icon.
4. **Follow the setup window:**
   - **Connect Claude.** It opens Terminal running Claude Code. Type `/login` and sign in with your Pro/Max account.
   - **Screen Recording.** Needed so Flippy can see your screen. Turn on **Flippy** in System Settings → Privacy & Security → Screen & System Audio Recording, then click **Restart Flippy** in the setup window.
   - **Accessibility.** Needed for `/act` desktop tasks and the double-tap ⌘ pause. Turn on **Flippy** in System Settings → Privacy & Security → Accessibility, then restart Flippy.
   - **Open at login** (optional).
5. **Take the tour.** It takes a minute and shows each feature. Replay it any time from the menu bar icon → **Take the tour**.

Default hotkeys: `⇧⌘Space` asks, `⌃⇧Space` circles something, `⌃⌥V` records a video edit to check, double-tap `⌘` pauses a walkthrough. Change them in Settings → Hotkeys. If one can't work (another app took it, macOS uses it for Spotlight or input sources, or double-tap needs Accessibility), the tour says so first and offers **Change…**, and the menu marks it with ⚠.

**If a permission is on but Flippy still says it's missing:** in that System Settings list, select Flippy, click **−** to remove it, then add `~/Applications/Flippy.app` again with **+** and restart Flippy. macOS remembers the exact build it approved, and an older Flippy (from a previous install or `Flippy.dmg`) can hold the entry. Delete any old copy first: `rm -rf /Applications/Flippy.app`.

### Linux (COSMIC)

Needs COSMIC on Wayland (Pop!_OS 24.04) and Python 3.11+. For `/act` desktop tasks, the real pointer and real glass, update to COSMIC Epoch 1.7 or newer first (`sudo apt full-upgrade`, then log out and back in).

1. **Install Flippy.** Paste this into a terminal (it asks for your password to install apt packages):

   ```bash
   curl -fsSL https://raw.githubusercontent.com/kap-il/flippy/main/install.sh | bash
   ```

2. **Log in to Claude.** Run `claude` once and sign in with your Pro/Max account. Don't set `ANTHROPIC_API_KEY`, or it bills the API instead.
3. **Add the hotkeys.** Run `~/.local/bin/flippy-ask setup` and let it add them, or add them yourself in COSMIC Settings → Keyboard → Keyboard shortcuts → Custom shortcuts. Use the full path:

   | Shortcut | Command |
   |---|---|
   | `Super+Shift+Space` | `~/.local/bin/flippy-ask` |
   | `Super+Alt` | `~/.local/bin/flippy-ask draw` |
   | `Super+P` (optional) | `~/.local/bin/flippy-ask pause-toggle` |
   | `Super+Shift+V` (optional) | `~/.local/bin/flippy-ask video` |

4. **Press `Super+Shift+Space`.** Flippy starts on the first press and its icon appears in the panel. To start it at login, turn on **Open Flippy at login** in `flippy-ask setup`. A shortcut that isn't set up, or whose keys COSMIC also uses, gets a ⚠ in the panel menu, and the tour offers to fix it.

The installer puts the code in `~/flippy`, builds gtk4-layer-shell into `~/.local` (Pop!_OS doesn't package it), links `flippy-ask` and `flippy-daemon` into `~/.local/bin`, and adds **Flippy** to the app library. If you put gtk4-layer-shell somewhere else, set `FLIPPY_LAYER_SHELL_LIB` to its library folder. The first time a task needs the pointer, COSMIC asks once to allow remote desktop. [docs/linux-port.md](docs/linux-port.md) explains how it all works there.

### Install options

- **Somewhere other than `~/flippy`:** `curl -fsSL https://raw.githubusercontent.com/kap-il/flippy/main/install.sh | FLIPPY_DIR=~/code/flippy bash`
- **Read it first:** `git clone https://github.com/kap-il/flippy && cd flippy && ./install.sh` does the same thing.
- Single monitor only for now, on both platforms.

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

Ask Flippy to do something ("open Spotify and play some jazz") and it does it, asking you first; ask how and it shows you. Questions and tips never touch your apps (see below). Flippy uses your existing **Claude Pro/Max subscription** through the Claude Agent SDK; no API client or key is added.

## Updates

Flippy checks GitHub for a new release once a day and shows a card (**Install / Later / What's new**). **Install** updates your copy and restarts Flippy. Check any time from the menu bar or panel icon (**Check for updates…**) or with `flippy-ask update`. You can also run the install command again; it pulls the latest code and rebuilds. Turn the daily check off with `updates.check = false`. If you've edited Flippy's files yourself, it won't overwrite them: update with `git pull` instead.

On macOS, rebuilding the app can make macOS ask for Screen Recording again (Flippy is signed ad hoc, not notarized).

Releasing (for maintainers): `scripts/release.sh 0.3 "what changed"` bumps `VERSION`, tags, pushes and publishes the GitHub Release. The notes' first line is what the update card shows.

## Usage

Press the ask hotkey (`⇧⌘Space` on macOS, `Super+Shift+Space` on COSMIC), type, hit Enter. `Up`/`Down` bring back earlier questions, like a terminal (kept in memory only, never on disk). The usual editing keys work in the box: `⌘A` `⌘C` `⌘X` `⌘V` `⌘Z` `⇧⌘Z` on macOS (`Ctrl` on COSMIC), word and line jumps with `⌥`/`⌘` and the arrows, `⌥⌫` and `⌘⌫`. `Esc` closes the box; answers fade on their own (or `flippy-ask dismiss`). Type `/new` for a fresh session or `/settings` for the settings window.

For draw mode, press the draw hotkey (`⌃⇧Space` / `Super+Alt`), drag to circle something, release, then type your question. Esc, right-click, the hotkey again, or 60 s of nothing cancels it.

### Approved desktop tasks

Just ask Flippy to do it: open the question box and type what you want done, for example `open Spotify and play some jazz` or `write a haiku in this note`. Flippy tells a request to *do* something apart from a question about *how*, and starts a desktop task for the first. It starts in the app you were in; it can open and switch to other apps itself. To force a task, start with `/act` (`/act type hello into this empty note`), or run `flippy-ask act <task>`. Turn the automatic part off in Settings → Desktop tasks → **Do things when I ask** (`act.infer = false`); `/act` keeps working.

Flippy takes a screenshot, proposes a click, short text entry, shortcut, scroll or drag, and shows the exact input and its reason. Non-ASCII and control characters are escaped; proposals too long to review are refused. **Allow once** permits only that input; **Stop** or leaving the card unanswered for 60 seconds ends the task. Every completed input returns a fresh screenshot to Claude. Press the ask hotkey again or run `flippy-ask dismiss` to cancel, including while typing or dragging. Cleanup releases only input posted by Flippy before another action can start.

This uses custom tools inside the existing Agent SDK, with the same configured model, effort, and Claude login. Each task gets its own session so tools and task history don't enter ordinary tutor conversations. Screenshots and tool turns consume your subscription limits. Screen Recording and Accessibility permissions are required; allow Flippy in macOS settings and restart it if needed.

The first version supports one display, at most 12 inputs per task and 160 characters per text entry, with a five-minute task timeout. Scroll uses 1–10 native wheel lines; drag follows a straight path for 0.6 seconds within the foreground window. Before dispatch, Flippy hides its preview, checks the original target geometry and compares the screen's decoded pixels with the proposed frame. Any difference stops the task, including blinking carets or animation. During drag, intentional window movement is allowed while the app, window and display must remain the same. These checks cannot eliminate the final dispatch race. Actions can affect documents or submit forms, so review every approval. Browser interaction uses your visible desktop and session; there is no browser extension or DOM driver.

On COSMIC, tasks work through the app's controls (AT-SPI, Linux's accessibility layer) without bringing it in front. Keys it can't send that way, and clicks on spots that aren't controls, wait until you pause for a second, bring the app forward for a moment and give your window back. Terminals, settings and password managers always ask before each input; browsers do too, except in **Act automatically** mode. How it works: [docs/linux-port.md](docs/linux-port.md#desktop-tasks-act).

## Isolated local demo

With the normal source dependencies installed in `.venv`, run `scripts/dev.sh build`, `run`, `ask <command>`, `stop` or `doctor`. `scripts/dev.sh --verify` builds, launches and checks the demo socket. Builds never install login items or initiate authentication.

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
| `act.infer` | `true` (default): a request to do something ("open Spotify and play jazz") runs as a desktop task without `/act`; `false`: only `/act` does |
| `act.mode` | `per_app` (default: approve each app once per task), `auto` (no approval cards, browsers included) or `every_input`. Terminals, settings and password managers ask before every input in every mode |
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
rm -rf /Applications/Flippy.app ~/Library/Application\ Support/Flippy   # an old Flippy.dmg install, if you had one
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
packaging/  make_icon.py: the app icon (Flippy.app's and COSMIC's); macos/: Flippy.app's launcher (Swift)
scripts/    the macOS and Linux installers, release.sh, package.sh (the per-platform release downloads)
tests/      python -m unittest discover tests
docs/       linux-port.md: how the macOS features work on COSMIC;
            linux-0.3.0.md: instructions for bringing COSMIC up to macOS (/act, pointer input, glass, the new look);
            linux-catch-up.md: what changed after 0.3.0 and how to update and check COSMIC;
            video-review.md: video review, and how to build it on macOS;
            errors.md: every error code Flippy shows, what it means and what to do
```

## Credits

- Pointing protocol and prompt adapted from [farzaa/clicky](https://github.com/farzaa/clicky) (MIT, Copyright (c) 2026 Farza). License text in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- [gtk4-layer-shell](https://github.com/wmww/gtk4-layer-shell) for the Linux overlay; [PyObjC](https://github.com/ronaldoussoren/pyobjc) for the macOS one.
- [VT323](https://fonts.google.com/specimen/VT323) font (SIL Open Font License, see `flippy/fonts/OFL.txt`).
