# Flippy 0.3.0 on COSMIC: instructions for the Linux session

Run this on the Pop!_OS COSMIC machine, in a Claude Code session in the Flippy checkout. It brings COSMIC up to
what macOS has on `main` and unblocks the two things `docs/linux-port.md` lists as blocked (pointer input,
Liquid Glass). Assume **COSMIC Epoch 1.7 or newer**: the RemoteDesktop portal (with libei pointer/keyboard input)
and the background-blur protocol both shipped in Epoch 1.7.0 (Aug 24–25, 2026).

macOS on `main` is ahead in two batches:

- **0.2.5**: `/act` desktop tasks (Parts 2–3 below).
- **PR #6, merged after 0.2.5**, which combined #3, #4 and #6:
  - Codex / ChatGPT as a second subscription, and the usage guard.
  - Setup opening only when needed, and error codes.
  - /act memory and scripted app actions.
  - The new black / gray-outline look, the Mono theme (now the default), and the Draw editor's smooth drawing and
    color picker.

  Part 1 checks what of that already runs here; Part 5 ports the rest.

When this lands, Kapil releases **0.3.0** for both platforms from macOS (`scripts/release.sh 0.3.0 "<notes>"`, from
main once your PR is merged). Don't release from Linux.

## Rules

- **macOS must run exactly what it runs today.** Everything new goes in `flippy/linux/`. Touch a shared file
  (`flippy/daemon.py`, `flippy/actions.py`, `flippy/settings.py`...) only where the controller needs a hook, keep
  the change platform-neutral, and run the full test suite. The Mac-only tests skip here; that's fine.
- **Never test on the user's real data.** Use windows you open yourself (a new gnome-text-editor document, a new
  Firefox window on about:blank). Close them afterwards without saving.
- **Ask before anything that shows the user's whole screen to Claude** (an `/act` run, a normal ask). Unit tests and
  direct calls to the platform functions don't need that.
- **Kill test processes by PID**, never `pkill -f <pattern>`. Stop Flippy with `flippy-ask quit` before running a
  second copy (see `docs/video-review.md`, "Mistakes not to make").
- **Keep tests importable on both platforms.** CI runs the suite on Ubuntu and macOS on every push
  (`.github/workflows/checks.yml`). A shared test must never import `flippy.mac.*` (AppKit doesn't exist on Linux)
  or `flippy.linux.*` (GTK isn't on the macOS runner); fake them, or `skipUnless` the platform.
- Work on a branch (`linux/0.3.0`), commit as you go, push, open a PR into `main`. Don't release; Kapil merges and
  releases 0.3.0.
- **Commit only after the test run prints `OK`.** A grep that only matches the summary line isn't enough.
- Write code like the surrounding code: short docstrings that say why, same naming and comment density.

## How /act works (read this code first)

`/act` landed on macOS in 0.2.5. The controller doesn't know about AX or Wayland; it calls a small platform
interface and the shared tool layer does the rest.

- `flippy/actions.py`: the tool contract. `BACKGROUND_CATALOG` (look, use_app, press, set_text, focus, type,
  key, menu, media, click, scroll, drag, app_action, remember), `BACKGROUND_PROMPT` (plus `act_memory.brief()`), `DesktopTools.invoke` (approval, limits, stop),
  `AppFrame` (one look: jpeg, size, target tuple, numbered elements, text), `RetryableActionError` (nothing was
  done: Claude gets the reason and a fresh look; the task goes on), `ApprovalPolicy` (per_app / auto /
  every_input, sensitive apps).
- `flippy/daemon.py`: `act()`, `_app_look`, `_app_perform`, `_action_approve`, `_action_done`, `_acting`.
- `flippy/mac/ax.py` and the `app_*` methods + `_borrow_pointer` in `flippy/mac/ui.py`: **the reference
  implementation you're porting.** Mirror its function names and behavior.
- Tests: `tests/test_background.py`, `tests/test_borrow_pointer.py`, `tests/test_actions.py`.

The Linux `Platform` (in `flippy/linux/ui.py`) must provide what the controller calls:

| Method | Does | macOS counterpart |
|---|---|---|
| `app_preflight()` | raise `ActionError` with a fix-it message if AT-SPI isn't reachable | `ax.trusted()` + post-event check |
| `app_front()` | `(app id, name, handle)` of the app in front, not Flippy | `ax.front_app()` |
| `app_open(name, cancel)` | find a running app by name, or launch it **without activating it**; returns `(id, name, handle, opened)` | `ax.open_app()` |
| `app_look(id, name, handle)` | `(jpeg b64 or None, image size, target, elements, text)` | `ax.look()` |
| `app_act(name, args, frame, cancel)` | press / set_text / focus / type / key / menu / media / click / scroll / drag | `Platform.app_act` |
| `app_name(id, handle)` | display name for approval cards | `Platform.app_name` |
| `action_card` | a second `Nudge`, separate from tips/updates; its `card()` must accept `width=` | `Platform.action_card` |

`target` is the tuple `(app id, handle, window id, (x, y, w, h), 0)`. The policy uses `target[0]` (app id) and
`target[1]`; `AppFrame.to_logical` maps screenshot pixels to `target[3]` (the window's geometry). On Linux the
handle can be the AT-SPI application object's process id, or an index into a dict the platform keeps; it just has
to be stable for the task.

## Part 1: smoke-test current main first (≈30 min)

Before building anything, check that `main` runs on COSMIC. A lot of shared code changed since anyone ran it here.
Fix anything broken as its own commit before going on.

1. `git pull` on main, `flippy-ask quit`, `scripts/install_linux.sh` (refreshes dependencies and the app-library
   icon: it's now the black-and-white hand with white click lines, no tile), start Flippy. Check
   `~/.local/state/flippy.log` for tracebacks.
2. Ask a question, circle and ask, video review (`Super+Shift+V`).
3. **Mono theme** (`flippy/themes.py` `Mono`, now the default):
   - The answer card is black with a gray outline and sharp corners.
   - The pointer is the grayscale hand. Picking "arrow" gives a grayscale arrow.
   - On a multi-step walkthrough: drag the seek and speed bars (the knob shows only while held), click the square
     prev / pause / next / close buttons, and click the outlined `1×` speed button (it steps through the speeds).
   - The question box matches the card (`Mono.box_css`).
4. **Setup opens by itself only on install, a new major version, or a lost login** (`flippy/setup_gate.py`, decided
   after the first login check):
   - Restart Flippy: setup must **not** open (you're an existing user; `~/.config/flippy/setup.json` should appear
     with `{"major": 0}`).
   - With `FLIPPY_PROFILE=demo` and an empty `~/.config/flippy-demo/`, it must open once.
5. **Codex / ChatGPT** (`flippy/codex_provider.py`, `flippy/providers.py`, `flippy/usage_guard.py`):
   - If `codex` (0.153.4 or newer) is installed and signed in with ChatGPT, setup and Settings → Models show it
     connected.
   - With Provider = Codex, an ask answers. The log shows no API-key use.
   - `codex_executable()` looks in `~/.local/bin`, npm, volta and bun dirs, because apps get a minimal PATH. Check it
     finds yours.
   - The usage guard needs nothing visible. It reads `account/rateLimits/read` before each Codex request, and Claude's
     rate-limit events.
6. **Error codes** (`flippy/errors.py`, `docs/errors.md`): failures show a sentence plus a code. Check one: with
   Provider = Codex and `codex` renamed away, an ask shows `… · CODEX-MISSING` and the log has a matching
   `error CODEX-MISSING: …` line.
7. `flippy-ask tour`: walk the whole tour. The cards must show the COSMIC shortcuts (from `key_label`), and it must
   end in Settings.
8. Settings: every page opens. "Desktop tasks" and the Models page's Provider / Codex rows exist.
9. `flippy-ask act hello` must answer "desktop tasks are available on macOS only for now" (Part 2 changes that).

## Part 2: /act through AT-SPI (≈1–1.5 h)

AT-SPI is Linux's accessibility layer (what screen readers use). GTK, Qt, Firefox, Chromium/Electron and
LibreOffice expose their controls through it; COSMIC's own apps (libcosmic/iced) expose little so far. Use it
through GObject introspection: `gi.require_version("Atspi", "2.0"); from gi.repository import Atspi`. Add
`gir1.2-atspi-2.0` and `at-spi2-core` to the apt line in `scripts/install_linux.sh`.

Create `flippy/linux/atspi.py` mirroring `flippy/mac/ax.py`:

- **Which app.** `Atspi.get_desktop(0)` children are the apps (`get_name()`, `get_process_id()`). The app in front
  comes from Wayland, not AT-SPI: `wl.connection().active()` gives the active toplevel's `app_id` and title (that's
  how `video_window` does it). Match it to an AT-SPI app by process (via `/proc/<pid>` and the toplevel), else by a
  frame whose name equals the toplevel's title. Write the matching as a pure function and unit-test it.
- **App ids.** Policy ids come from `actions.app_id()`, which only accepts dotted ids (macOS bundle ids). Wayland app
  ids are often dotted (`org.gnome.TextEditor`) but not always (`firefox`). Anything rejected counts as *sensitive*
  (asks before every input), so add a Linux-safe variant in `flippy/linux/` rather than loosening the shared
  regex, or extend `app_id` so bare lowercase names are accepted **only** when a `linux` flag is passed. Keep macOS
  identical. Also add Linux equivalents to `ApprovalPolicy.SENSITIVE`'s idea of sensitive apps: terminals
  (`com.system76.CosmicTerm`, `org.gnome.Ptyxis`, `kitty`, `Alacritty`, `org.wezfurlong.wezterm`), COSMIC
  Settings (`com.system76.CosmicSettings`), browsers (`firefox`, `org.mozilla.firefox`, `google-chrome`,
  `chromium`, `brave-browser`), password managers (`org.keepassxc.KeePassXC`, `com.bitwarden.desktop`,
  `1password`). Do this with a Linux list consulted when the target is a Linux one, so macOS behavior doesn't move.
- **Seeing the window.** Screenshot: `wl.connection().capture_window(toplevel)` (the same capture video review uses;
  it works for windows behind others). Controls: walk the matching AT-SPI frame's tree like `ax.look` (depth/visit
  caps, the same role filter: push buttons, toggle buttons, check/radio, text, entry, combo box, menu items, links,
  list items, table cells, tabs, sliders, labels). For positions use **window coordinates**,
  `get_extents(Atspi.CoordType.WINDOW)`: on Wayland, `SCREEN` coordinates aren't real. Window coords map straight
  onto the window capture. Window geometry for `target[3]` comes from the toplevel (`wl.py` already tracks it for
  help mode, as `(x, y, w, h)` relative to its output: add the output's position when mapping to the stream). Write the same text block as `ax.look` (app, window state, menus with their items, numbered controls
  with what you can do to each), so `BACKGROUND_PROMPT` works unchanged.
- **Menus.** GTK/Qt menu bars are in the AT-SPI tree (`menu bar` → `menu` → `menu item`). Implement `menu(path)`
  like `ax.menu`: match titles case-insensitively, report the choices when one isn't found, skip disabled ones with
  a "greyed out" `RetryableActionError`, `do_action(0)` the item. GTK4 apps without a menu bar have a "primary menu"
  button instead; Claude can press it.
- **press**: the Action interface, `do_action(i)` for the action named `click`/`press`/`activate`.
- **set_text**: the EditableText interface, `set_text_contents`.
- **focus**: Component `grab_focus()`.
- **type**: insert at the caret: `Text.get_caret_offset()` + `EditableText.insert_text(offset, text, len)`.
  Background-safe. If the control has no EditableText, fall back to Part 3's borrowed focus + virtual keyboard.
- **key**: Wayland has no "send a key to one app". Do it through Part 3's borrow: activate the window, send the key
  with `flippy/linux/keyboard.py` (the virtual keyboard Flippy already has), give focus back.
- **media**: MPRIS over D-Bus (dbus-python is already a dependency for the tray): list
  `org.mpris.MediaPlayer2.*` names, prefer the one whose `PlaybackStatus` is `Playing`, call
  `org.mpris.MediaPlayer2.Player.PlayPause` / `Next` / `Previous`. No window or pointer needed.
- **use_app**: launch hidden from the user's focus: `gtk-launch <desktop id>` or `Gio.DesktopAppInfo` `.launch()`;
  then wait (≤10 s) for the AT-SPI app and a toplevel to appear, like `ax.open_app`. Find the desktop entry by
  name with `Gio.AppInfo.get_all()`.
- **Enabling a11y in apps that hide it.** Chromium/Electron and some Qt apps only expose their tree when a screen
  reader seems present. Setting `org.a11y.Status.IsEnabled = true` on the a11y bus is the standard switch (GTK/Qt
  honor it). Do **not** flip `ScreenReaderEnabled` globally without asking: it changes behavior in every app. If an
  app shows almost nothing, the look says so and Claude falls back to clicks (Part 3), as on macOS with Spotify.

**Also on macOS since 0.2.5, port these too:**

- **Scripted app actions** (the `app_action` tool; `flippy/mac/scripts.py` runs fixed AppleScript snippets). Make a
  `flippy/linux/scripts.py` with the **same action names** where Linux can do them, and have the Linux catalog's
  `app_action` description list only those:
  - Spotify and other players through **MPRIS**:
    - `spotify.play_pause` / `next` / `previous`
    - `spotify.shuffle_on` / `shuffle_off`: the `Shuffle` property
    - `spotify.play_uri`: `OpenUri` with a `spotify:` URI
    - `spotify.now_playing`: `Metadata` `xesam:title` / `xesam:artist`, and `PlaybackStatus`
  - `spotify.open_search`: `xdg-open spotify:search:<url-encoded query>`.
  - `safari.open_url`: rename it in the Linux catalog to a browser-neutral `browser.open_url` with
    `Gio.AppInfo.launch_default_for_uri`, http(s) only.
  - Leave out `music.*`, `notes.*` and `mail.*`.
  - Keep the same rule: values go in as arguments, never into a command string; validate URIs like
    `scripts._check`.
- **Per-app memory** (`flippy/act_memory.py`): no work. It runs inside `DesktopTools`, so it works as soon as /act
  does. Just check that app ids you pass as `target[0]` are stable across runs: the memory is keyed by them.
- **Stop reasons and error codes**: raise refusals with the same reason codes as macOS (`ActionError.code`, e.g.
  `input_held`, `permission`), so `errors.ACT_REASONS` turns them into `ACT-HELD`, `ACT-PERMISSION`… Don't add
  Linux-only codes without adding them to `errors.CODES` **and** `docs/errors.md` (a test checks).

Wire the Platform methods in `flippy/linux/ui.py`, give the Linux `Nudge.card` a `width=None` keyword it accepts,
add `self.action_card = Nudge(self.overlay)` (a second instance), and update the "Desktop tasks" description in
`flippy/linux/settings_window.py` so it no longer says macOS only.

Tests (no desktop needed): the app/toplevel matching, the look text from a fake tree, menu path matching and
choices, the MPRIS player choice, the Linux app-id/sensitive rules. Live checks with your own text-editor window:
look lists its controls, set_text, insert at caret, press a toolbar button, a menu item, all while another window
stays in front.

## Part 3: real pointer and keyboard through the RemoteDesktop portal (≈1 h)

Epoch 1.7's `xdg-desktop-portal-cosmic` implements `org.freedesktop.portal.RemoteDesktop`, with pointer and
keyboard events delivered over libei. This replaces "Scripted mouse: blocked" in `docs/linux-port.md`.

- **Session.** `CreateSession` → `SelectDevices(types=KEYBOARD|POINTER, persist_mode=2)` → ScreenCast
  `SelectSources(types=MONITOR)` on the **same** session (absolute pointer motion needs a stream) → `Start`. The
  user approves once in COSMIC's dialog; keep the returned `restore_token` in Flippy's config (it's a credential:
  store it with 0600 permissions, never log it) and pass it on the next `SelectDevices` so there's no dialog again.
  Follow `flippy/linux/recorder.py` for the portal request/response pattern; it already drives ScreenCast.
- **Input.** `NotifyPointerMotionAbsolute(session, {}, stream, x, y)` in the stream's coordinates,
  `NotifyPointerButton(session, {}, BTN_LEFT=0x110, 1/0)`, `NotifyPointerAxisDiscrete` for scroll,
  `NotifyKeyboardKeycode` for keys. Map window coords + the toplevel's geometry to the stream's (monitor) space.
- **Use it for:**
  1. `flippy-ask click/move/path` (`automation.clicks`), finishing what `docs/linux-port.md` described.
  2. `/act` click / scroll / drag. **Wayland has no pointer-free path to a background window** (no
     `CGEventPostToPid` equivalent), so on COSMIC every position-based action is the borrowed kind. Port
     `_borrow_pointer`: wait for the user to be idle ≥1 s (`wl.py` already binds `ext_idle_notifier_v1` for help
     mode: seconds since the last input), activate the target toplevel (bind `zcosmic_toplevel_manager_v1` in `wl.py`, which today
     only binds toplevel *info*, and call its `activate(toplevel, seat)`), check it's on top at that spot, do the input, then **activate
     the previously active toplevel again**. Wayland doesn't let clients read the pointer's global position, so it
     can't be put back exactly: leave it where it ended up and say so in the docstring. Give up after 45 s of the
     user working, with a `RetryableActionError`, exactly like macOS.
  3. `/act` `key` and the `type` fallback, through the same borrow (activate → virtual keyboard → reactivate).
- **Borrow as rarely as possible.** Wayland has no way to click a background window without the real pointer and
  focus, so on COSMIC every position-based action costs a focus flash. Keep them rare:
  1. **Controls before positions.** When Claude clicks a spot, first hit-test the AT-SPI tree at that window
     position (`Component.get_accessible_at_point(x, y, Atspi.CoordType.WINDOW)`); if it's a pressable control,
     `do_action` it in the background, exactly like `ax._press_at` on macOS. Only borrow when nothing pressable is
     there.
  2. **Menus and text before keys.** Typing goes in through `EditableText` at the caret; most shortcuts have a menu
     item the `menu` tool picks without focus. Say so in the Linux prompt wording.
  3. **Batch.** If Claude sends several position actions in a row, do them in one borrow (activate once, do them
     all, reactivate once) instead of one flash each.
- Because every click borrows focus on Linux, make the click tool's description say so on Linux, or have
  `real_pointer: false` behave like `true` there. Don't change the macOS catalog: give the Linux Platform a flag the
  controller passes into `DesktopTools` (`catalog=`) if the wording has to differ.

Tests: the idle wait, the give-up, refusing when another toplevel covers the spot, reactivating the previous window
even when the input fails (port `tests/test_borrow_pointer.py`). Live: approve the portal dialog once, restart
Flippy, confirm no second dialog, `flippy-ask click` a button in your own test window.

## Part 4: real Liquid Glass (optional; ≈45 min, skip if it fights you)

Epoch 1.7's cosmic-comp supports the background-effect (blur) protocol. Check it's advertised:
`wayland-info | grep -i background_effect`.

- The overlay is a GTK4 layer-shell surface. The blur request has to be made on **GTK's own Wayland connection**
  (the `wl_surface` belongs to it), not on `wl.py`'s separate connection. Get them from GDK
  (`GdkWayland.WaylandDisplay.get_wl_display()`, `GdkWayland.WaylandSurface.get_wl_surface()`) and bind
  `ext_background_effect_manager_v1` on that display. If pywayland can't wrap GTK's display pointer, a tiny
  C helper built with `wayland-scanner` is acceptable; keep it optional (feature off when it can't load).
- Each frame, set the blur region to the answer card's rect (and the lens / glass-hand shapes), the same rects
  `_place_glass` uses on macOS. Then set `has_backdrop = True` on the Linux `Overlay`, so the Glass and Media
  Player themes and `look.glass_tint` / `look.glass_color` / `look.player_shine` render for real.
- If it isn't advertised or fails, keep today's painted look. Never crash the overlay over it.

## Still blocked: shortcuts from Flippy's settings

COSMIC has no GlobalShortcuts portal, so Flippy keeps writing its shortcuts into
`~/.config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom` (setup offers that today), and pause stays a
normal shortcut (no double-tap on Wayland). No work here; update `docs/linux-port.md` to say it's by design.

## Part 5: the new look and the Draw editor on GTK (≈1–1.5 h)

On macOS, setup, Settings and the Draw editor now share one look. The GTK windows (`flippy/linux/setup_window.py`,
`settings_window.py`, `pointer_editor.py`) still look like before #6. Bring them to the same design.
Use GTK CSS on Flippy's own windows only (a style provider on each window or a `flippy` CSS class), never the
user's theme.

**The look.** References: `flippy/mac/setup_style.py`, `setup_window.py`, `settings_window.py`.

- **Colors:**
  - background `#000000`
  - outlines `rgb(128,128,133)` (`OUTLINE = (0.50, 0.50, 0.52)`)
  - dividers `rgb(56,56,59)`
  - text `rgb(240,241,242)`, muted text `rgb(158,163,173)`
  - pressed `rgb(41,41,43)`
- **Shapes:** every button, popup / dropdown, entry, checkbox, card and keycap is black with a 1 px outline and
  **0 radius**. Section numbers sit in an outlined **diamond** (rhombus).
- **Selected state:** selected tabs and the selected tool get a brighter outline (the text color) and white text;
  the others are muted.
- **Settings tabs:** pages switch with a row of outlined buttons along the top that share edges. On GTK, a
  `Gtk.StackSwitcher` styled flat works.
- **The hand mark:** the header icon and the Permissions card's app icon are the gray pixel hand with gray click
  lines and no tile. Draw it with the same code as `setup_style.flippy_mark`; move the drawing into a shared
  cairo helper if that's simplest.

**Setup content** (port the macOS behavior, not just the look):

- **Provider cards:**
  - Show "Connected" / "Not connected" with **Reconnect…** / **Log in…** (Claude) or **Sign in…** (ChatGPT).
  - Even padding on all sides, with everything vertically centered.
  - Delete the stale Linux subtitle "Included-only credit enforcement is still under verification": the usage guard
    does it now.
- **The line under Use:**
  - With both connected and Use on Automatic, it says *"Both are connected. Pick Claude or ChatGPT under Use to
    finish setup."* in bright text, and the Use dropdown gets a 2 px bright outline.
  - If the chosen provider isn't connected, it says so.
  - Otherwise it's a muted "You can switch any time in Settings → Models."
- **Shortcut section:**
  - Keycaps for the ask shortcut.
  - Under them, *"There are more, like circling something or checking a video. Change any in Edit…"*.
  - Edit… opens Settings → Hotkeys. On COSMIC the shortcuts live in COSMIC Settings, so word it to match.
- **Launch at login:** the switch on the right, its edge lined up with the buttons.

**Draw editor** (`flippy/linux/pointer_editor.py`). It still has its own grid code. Move it onto the shared model
`flippy/pixelart.PixelArt` (the macOS editor already uses it), which now does both styles:

- **Style: Pixels | Smooth**, plus **Thin / Medium / Thick** brushes (greyed in Pixels):
  - `art.set_pixel(bool)` and `art.brush`.
  - In Smooth: `stroke_to(x, y, color, mirror)` while dragging and `end_stroke()` on release.
  - Fill is `fill_smooth`.
  - The tip stays on the grid (`hotspot` is a cell).
  - Saving writes `grid_h`, so a smooth pointer shows as big as a pixel one.
  - Tests: `tests/test_smooth_drawing.py`.
- **Color:**
  - The palette swatches.
  - A current-color swatch.
  - A **hex** entry: `#RGB` / `#RRGGBB`, applied on Enter; reuse `to_hex` / `from_hex` from the macOS editor, or
    move them to `pixelart`.
  - **H/S/B** sliders with gradient tracks, and an **RGB** button that swaps them for R/G/B sliders in whole 0–255
    steps, with the value shown beside each.
  - An **Eyedropper** through the Screenshot portal's `PickColor` (`org.freedesktop.portal.Screenshot`). The user
    clicks anywhere on screen and you get an RGB triple. Follow `recorder.py`'s request/response pattern.
- **Same look** as above. The canvas keeps its checkerboard; the grid shows faintly in Smooth.

Tests: whatever is pure (hex parsing, the slider ↔ color math, the PickColor response parsing). Check the windows
live (screenshots are fine: they don't need Claude). Ask Kapil to compare with the macOS ones.

## Finish

1. Update `docs/linux-port.md`:
   - The table: pointer is yes via RemoteDesktop; Liquid Glass is yes if Part 4 landed; `/act` is yes, through
     AT-SPI, and every click borrows focus; Codex is yes.
   - Replace the "Blocked" sections.
2. Full test suite green: `.venv/bin/python -m unittest discover tests` prints `OK`.
3. One live end-to-end `/act` run, **after asking Kapil** (it sends his screen to Claude). For example, "open Text
   Editor and write a haiku in a new document". Then a second, similar task in the same app: the log should show it
   starting from what worked (`act_memory.json` has the app).
4. Push `linux/0.3.0` and open a PR into `main`. Say what works, what was tested live, and the known limits:
   COSMIC's own apps expose little to AT-SPI; the pointer isn't put back exactly; Glass works only if Part 4
   landed. Kapil merges it and releases 0.3.0.

Estimate: CC ≈ 5–6 h over three sessions:
- Part 1, then Part 2 with its app actions
- Parts 3–4
- Part 5

Kapil's time: approving the portal dialog once, about 20 min testing apps, and about 10 min comparing the GTK
windows with macOS.
