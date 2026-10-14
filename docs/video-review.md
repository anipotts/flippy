# Video review

"Did I do this edit right?" You press a shortcut in your video editor, play the edit
back, press it again and ask. Flippy shows Claude the frames that matter and the card
answers, pointing at your timeline if that helps.

Works on COSMIC (`Super+Shift+V`, tested end to end; see [What was tested](#what-was-tested)) and macOS
(`⌃⌥V`, menu bar "Check a video edit"); see [The platforms](#the-platforms).

## How it works

Claude takes text and images, not video or audio. So video review is a frame picker:

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
5. **Ask.** The frames go to Claude in the normal session, followed by a regular
   screenshot of the screen as it is now. That screenshot is what `[POINT]` tags refer to,
   so the normal playback code points and plays the answer. The prompt
   (`ASK_TEMPLATE`) says what Claude can't judge: motion, sub-quarter-second timing,
   audio.

All of that is `flippy/video.py`. It's platform-neutral; `tests/test_video.py` covers the
picking on synthetic thumbnails.

### The parts

| Piece | Where | Platform? |
|---|---|---|
| Recording buffer, preview/cut detection, frame picking, prompt, multi-image ask | `flippy/video.py` (`Recording`, `preview_box`, `step_scores`, `find_cuts`, `pick`, `prepare`, `question`) | shared |
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
can ask about it again. Follow-up questions through the normal box share the session,
so Claude still has the frames in context.

## How it was built

Video means recording while the edit plays (not an exported file), with no audio. The picking is pure functions,
tested on synthetic thumbnails first. Each platform records the editor's **window**, not the screen, so Flippy's
overlay, its "Recording" card and the panel never end up in the frames. `Review` drives the controller through the
attributes and methods the normal ask uses (`busy`, `gen`, `shooter`, `_run`, `_start_playback`, `_stream_text`,
`_on_answer`, `_fail`, `overlay`), and asks through the shared `brain.ask` with the frames as `extra_images`, in the
same session. `Flippy` owns `self.video` and routes `video …` (`NOT_HERE` without `video_window`).
Still open: moving `Review`'s use of those private methods into a public `Flippy.ask_with(...)`, so the normal ask
and video review share one path.

## Mistakes not to make

These all happened (or nearly did) while building the COSMIC side:

- **Don't change shared files or `flippy/mac/` for one platform's sake.** Extend from the
  platform folder (a mixin, a wrapper, a new module) so the other platform runs what it
  ran before. Shared changes go in only when both sides are ready.
- **Don't record or screenshot someone's screen without saying so first.** Test with a
  window you opened yourself (a generated clip in a player). The final screenshot shows
  the whole screen, so ask before a live test.
- **Check for a running Flippy before starting a test copy.** A second daemon unlinks and
  rebinds the socket (`SOCK_PATH`), so the first one keeps running but can't be reached,
  and the next shortcut starts a third. Stop it with `flippy-ask quit` first, or test
  under another `XDG_RUNTIME_DIR`.
- **Kill test processes by PID, not `pkill -f <pattern>`.** The pattern matches the
  shell running the command and kills it halfway through.
- **Don't promise audio.** Claude can't hear. Numbers about audio (loudness, silence) are
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

## The platforms

- **COSMIC:** `ext_image_copy_capture` with a toplevel source (`flippy/linux/wl.py` `capture_window`), the same
  capture help mode uses.
- **macOS** (`flippy/mac/ui.py`): `video_window` takes the frontmost app's first layer-0 window, front to back
  (`sensors.front_window(pid)`), and refuses Flippy's own. `video_frame` grabs that one window with
  `CGWindowListCreateImage` (`kCGWindowImageNominalResolution`, so Retina windows stay at 1×; still works on
  macOS 27, ~16 ms a grab) and falls back to `screencapture -l <id>` if it ever stops returning frames. The
  shortcut is `keys.video` (`ctrl+option+v`; `⇧⌘V` is "paste and match style" in many Mac apps), hotkey id 3, with
  a recorder row in Settings → Hotkeys and "Check a video edit" in the menu bar.

To try it on macOS, open a clip in QuickTime and play it, then:

```
flippy-ask video start
# ...let it play ~10 s...
flippy-ask video ask "where are the cuts, and are they clean?"
```

The log (`~/Library/Logs/flippy.log`) shows the answer. `flippy-events.jsonl` shows
`video_start` / `video_stop` (with seconds and frames) / `video_ask`. A generated test
clip with known cuts:

```
ffmpeg -f lavfi -i testsrc2=size=960x540:rate=30:duration=5 -f lavfi -i smptebars=size=960x540:rate=30:duration=5 \
  -f lavfi -i "mandelbrot=size=960x540:rate=30" -filter_complex \
  "[2]trim=duration=5,setpts=PTS-STARTPTS[m];[0][1][m]concat=n=3:v=1:a=0[v]" -map "[v]" -pix_fmt yuv420p clip.mp4
```

## What was tested

- `tests/test_video.py`: preview detection, cuts, frame picking, command parsing.
- Live on COSMIC (Pop!_OS 24.04, cosmic-comp, Opus 5.5 at low effort): the generated clip
  looping in `ffplay`, 13 s recorded at 4 fps, ~25 s from asking to the answer, all
  three cuts found at the right times.
- Not tested yet: a real editor (Kdenlive, Shotcut, DaVinci Resolve) with its UI around
  the preview, very long recordings near `MAX_SECONDS`, and fullscreen preview.
