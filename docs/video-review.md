# Video review: how it works, how it was built, and the macOS version

"Did I do this edit right?" You press a shortcut in your video editor, play the edit
back, press it again and ask. Flippy shows the selected model the frames that matter and the card
answers, pointing at your timeline if that helps.

Current implementation uses the same serialized, tool-free model request as
ordinary questions. Picked frames precede the current screenshot in chronological
order; `[POINT]` coordinates refer only to that final screenshot. Request ownership
covers recording/capture, streaming and playback cancellation.

Historical platform evidence from the 2026-10-07 source notes (`5ec1f26`):
**COSMIC was tested end to end**; **macOS was built** (`⌃⌥V`, menu bar
"Check a video edit"). This is not acceptance evidence for the current integrated
revision or the Codex adapter. See [What was tested](#what-was-tested) and
[The macOS version](#the-macos-version).

## How it works

The review sends text and selected still images, not raw video or audio. Its frame picker works as follows:

1. **Record.** While recording, the platform grabs the editor's window `FPS` (4) times a
   second. Each grab becomes a 1600 px JPEG in memory, plus a 96×54 grayscale thumbnail.
   Nothing is written to disk. It stops itself after `MAX_SECONDS` (90).
2. **Find the preview.** The thumbnail pixels that changed (by more than `CHANGE`) in at
   least `PREVIEW_SHARE` of the steps are the video viewer. Its bounding box is the
   crop (`preview_box`). A still UI with a blinking cursor gives no preview, and the
   whole window is used.
3. **Find the cuts.** The mean change inside the preview between neighbouring frames
   (`step_scores`). A cut is a local peak at least `CUT_MIN` and `CUT_OVER_MEDIAN` (3×)
   above the typical step (`find_cuts`). At most `MAX_CUTS`, biggest first.
4. **Pick frames.** Before and after each cut, the first and last frame, then evenly
   spaced frames up to `MAX_FRAMES` (12) (`pick`). Each is cropped to the preview,
   shrunk to 1024 px and labelled with its time (`prepare`).
5. **Ask.** The frames go through `Brain.ask(..., extra_images=...)` in the normal conversation, followed by a regular
   screenshot of the screen as it is now. That screenshot is what `[POINT]` tags refer to,
   so the normal playback code points and plays the answer. The prompt
   (`ASK_TEMPLATE`) says what the model can't judge: motion, sub-quarter-second timing,
   audio.

All of that is `flippy/video.py`. It's platform-neutral; `tests/test_video.py` covers the
picking on synthetic thumbnails.

### The parts

| Piece | Where | Platform? |
|---|---|---|
| Recording buffer, preview/cut detection, frame picking, prompt, multi-image ask | `flippy/video.py` (`Recording`, `preview_box`, `step_scores`, `find_cuts`, `pick`, `prepare`, `question`, `ask`) | shared |
| The feature: commands, recording thread, cards, question box, asking, playback | `flippy/video.py` `Review` | shared |
| Which window to record | `Platform.video_window() -> (handle, app name)` or `(None, why not)` | **per platform** |
| A grab of that window | `Platform.video_frame(handle) -> PIL.Image or None` (worker thread; `None` = window gone, stops) | **per platform** |
| The "Recording…" / "Your edit is ready" cards | `ui.nudge.card(...)` / `ui.nudge.hide()` (help mode's card; same API on both) | per platform, exists |
| Routing `video …` commands to `Review` | `Flippy.command` (`NOT_HERE` without `video_window`) | shared |
| Shortcut, menu item | COSMIC: `Super+Shift+V` → `flippy-ask video` (setup offers it), panel menu "Check a video edit". macOS: `keys.video` (`ctrl+option+v`), hotkey id 3, menu bar "Check a video edit" | per platform |

### Commands

```
flippy-ask video            start recording the window in front; again: stop and open the question box
flippy-ask video start      start
flippy-ask video stop       stop and open the question box
flippy-ask video ask <q>    stop if recording, then ask about the last recording without the box
flippy-ask video cancel     stop and throw the recording away
```

The last recording is kept in memory (until the next one or `cancel`), so `video ask`
can ask about it again. Follow-up questions use the ordinary conversation. Claude
keeps its active transport in memory without session persistence. After an
interruption, Flippy retains bounded text context including the marked partial
answer, closes the old transport and starts a new one. The recording remains in
memory until canceled or replaced; ask through `video ask` to resend its frames.
The Codex route has separate live acceptance and funding gates; it is not proven
by the historical Claude run.

## Historical implementation notes (2026-10-07)

1. Asked what "video" should mean. Answer: record while playing (not an exported file),
   no audio, COSMIC now and macOS built separately.
2. Kept macOS byte-identical: everything new is either a **new** shared module that
   macOS doesn't import yet (`flippy/video.py`) or lives in `flippy/linux/`. The
   controller (`flippy/daemon.py`) and `flippy/brain.py` weren't changed.
   - `Brain.ask` sends one image, so `video.ask` talks to `brain.client` itself, in the
     same session.
   - `Review` drives the controller through the attributes and methods the normal ask
     uses (`busy`, `gen`, `shooter`, `_run`, `_start_playback`, `_stream_text`,
     `_on_answer`, `_fail`, `overlay`). Those are private, which is the price of not
     touching `daemon.py`. See [Merging the two](#merging-the-two).
3. Recorded the **window**, not the screen. On COSMIC: `ext_image_copy_capture` with a
   toplevel source (`flippy/linux/wl.py capture_window`), the same capture help mode
   uses. Flippy's own overlay, its "Recording" card and the panel aren't in a window
   capture, so they never end up in the frames.
4. Wrote the picking as pure functions and tested them on synthetic thumbnails first.
5. Tested end to end: a generated 15 s clip with three shots looping in a player
   window, recorded 13 s, asked "where are the cuts". Claude found all three, at the
   right times, called them clean hard cuts, and said what it couldn't check.

## Mistakes not to make

These all happened (or nearly did) while building the COSMIC side:

- **Don't change shared files or `flippy/mac/` for one platform's sake.** Extend from the
  platform folder (a mixin, a wrapper, a new module) so the other platform runs what it
  ran before. Shared changes go in only when both sides are ready (see below).
- **Don't record or screenshot someone's screen without saying so first.** Test with a
  window you opened yourself (a generated clip in a player). The final screenshot shows
  the whole screen, so ask before a live test.
- **Use an isolated test profile.** The current demo has separate config, socket and
  logs. Instance ownership refuses an active listener and never removes a non-socket
  path. The original implementation lacked that protection, so its test instructions
  required stopping the first copy or changing `XDG_RUNTIME_DIR`.
- **Kill test processes by PID, not `pkill -f <pattern>`.** The pattern matches the
  shell running the command and kills it halfway through.
- **Don't promise audio.** The review sends no audio. Numbers about audio (loudness, silence) are
  possible later, but "does it sound right" isn't.
- **Synthetic test data has to look like the real thing.** The first cut test used
  "motion" that changed every preview pixel each frame, which real footage at 4 fps
  doesn't, and the cut rule looked broken. Motion should be small next to a cut.
- **Cards need at least one button.** macOS's `Nudge.card` takes `max()` over the
  buttons. `Review` always passes one; keep it that way.
- **Let the screen settle before the final screenshot.** `Review` waits
  `ui.hide_settle_ms` after hiding the box, like the normal ask.
- **Don't send every frame.** Each image costs subscription usage. 12 frames + 1
  screenshot is the cap; raise `MAX_FRAMES` only with a reason.
- COSMIC-only gotchas, for reference: capture buffers come as `XB24`/`AB24`, not
  `XRGB8888`; toplevel state arrives a moment after the first roundtrip; a capture
  session that reports "stopped" must not be destroyed twice, or the compositor drops
  the connection.

## The macOS version

The following describes the original build recorded on 2026-10-07, not a new
verification of the current platform or deployment target. Built as planned below. `video_window` uses `sensors.front_window(pid)` (first layer-0
window of the frontmost app, front to back); `video_frame` uses `CGWindowListCreateImage`
(still works on macOS 27, ~16 ms a grab) and falls back to `screencapture -l <id>` if it
ever stops returning frames. `flippy/video.py` is used as is.

### 1. `Platform.video_window()` (flippy/mac/ui.py)

The frontmost app and its frontmost normal window. `sensors.frontmost()` already gives
`(bundle id, name, pid)`, and `sensors.windows(pid)` the app's on-screen windows (id,
bounds), largest first. For the recording, take the frontmost of them in z-order rather
than the largest: `CGWindowListCopyWindowInfo` returns windows front to back, so the
first layer-0 window with that pid. Refuse Flippy's own pid (`os.getpid()`), like
`sensors.sample()` does, and return `(None, "Click your video editor first…")`.
Return `(window id, app name)`.

### 2. `Platform.video_frame(window_id)` (worker thread)

One window, without anything above it:

```python
img = Quartz.CGWindowListCreateImage(Quartz.CGRectNull, Quartz.kCGWindowListOptionIncludingWindow, window_id,
                                     Quartz.kCGWindowImageBoundsIgnoreFraming | Quartz.kCGWindowImageNominalResolution)
```

`None` (or a 1×1 image) means the window closed: return `None`. Convert the `CGImage` to
PIL from its data provider (`CGImageGetDataProvider` → `CGDataProviderCopyData`,
`CGImageGetBytesPerRow`, BGRA): `Image.frombuffer("RGBA", (w, h), data, "raw", "BGRA",
bytes_per_row, 1)`. `kCGWindowImageNominalResolution` keeps Retina windows at 1×, which
is plenty: frames are cut to 1600 px anyway.

It uses the Screen Recording permission Flippy already has. `CGWindowListCreateImage` is
deprecated from macOS 14 in favour of ScreenCaptureKit; check that it still returns
frames on the macOS you test on. If it doesn't, use `SCScreenshotManager
captureImageWithFilter:configuration:` with `SCContentFilter
initWithDesktopIndependentWindow:` (macOS 14+). That's async, so wait on a
`threading.Event` inside `video_frame`. The cards are a separate panel on macOS, and a
single-window capture leaves them out, like on COSMIC.

### 3. Routing, shortcut, menu

- **Routing:** see [Merging the two](#merging-the-two). Doing that first is simplest.
- **Shortcut:** a `keys.video` setting (`settings.DEFAULTS["keys"]`), registered in
  `Platform._bind_keys` as hotkey id 3 (1 and 2 are ask and draw, 4 is Esc while
  drawing), sending `self.command("hotkey video")`. `Flippy.command`'s `hotkey` branch
  already passes the name on (`self.command(name)`), so that reaches `video`. Pick the
  default with care: `⇧⌘V` is "paste and match style" in many Mac apps. `⌃⇧V` or
  `⌃⌥V` are safer.
- **Settings → Hotkeys:** a recorder row for `video`, like ask and draw
  (`flippy/mac/settings_window.py`, the `for name, what in …` loop).
- **Menu bar:** "Check a video edit" with command `video` in `MENU`
  (`flippy/mac/ui.py`), with its key shown like ask and draw.

### 4. Try it

Open a clip in QuickTime and play it, then:

```
flippy-ask video start
# ...let it play ~10 s...
flippy-ask video ask "where are the cuts, and are they clean?"
```

The original build logged the answer. Current default diagnostics contain metadata
only, without questions, answers or frames. Observe the answer in the card.
`flippy-events.jsonl` records allowlisted event metadata; detailed recording requires
an explicit process option. A generated test clip with known cuts:

```
ffmpeg -f lavfi -i testsrc2=size=960x540:rate=30:duration=5 -f lavfi -i smptebars=size=960x540:rate=30:duration=5 \
  -f lavfi -i "mandelbrot=size=960x540:rate=30" -filter_complex \
  "[2]trim=duration=5,setpts=PTS-STARTPTS[m];[0][1][m]concat=n=3:v=1:a=0[v]" -map "[v]" -pix_fmt yuv420p clip.mp4
```

## Merging the two

The historical routing merge gave `Flippy` one `video.Review` and removed the
COSMIC routing stopgap. The current integration also removes direct SDK calls
from video review: `video.ask` delegates to `Brain.ask` with ordered extra images.
Recording and inference acquire request ownership before capture; the final
screen uses the shared frame pipeline. Late callbacks from canceled requests
cannot update a newer request's playback.

`Review` still coordinates with the controller's capture and playback methods.
This refactor does not claim that its entire controller interface is public.

## What was tested

These are the original 2026-10-07 results, retained for provenance. They do not
verify the current merged app, supported macOS versions or live Codex behavior.

- `tests/test_video.py`: preview detection, cuts, frame picking, command parsing.
- Live on COSMIC (Pop!_OS 24.04, cosmic-comp, Opus 5.5 at low effort): the generated clip
  looping in `ffplay`, 13 s recorded at 4 fps, ~25 s from asking to the answer, all
  three cuts found at the right times.
- Not tested yet: a real editor (Kdenlive, Shotcut, DaVinci Resolve) with its UI around
  the preview, very long recordings near `MAX_SECONDS`, and fullscreen preview.
