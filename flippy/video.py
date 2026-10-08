"""Video review: record the editor while they play their edit back, then ask Claude about it.

"Did I do this edit right?" Flippy can't watch video the way a person does, and
Claude takes no audio or video, only images. So while the edit plays, Flippy grabs
the editor's window a few times a second (in memory, never to disk), then picks
the frames worth showing:

  1. the preview: the part of the window that kept changing while it played
     (the video viewer), so the frames sent are cropped to it, not the whole UI;
  2. cuts: the biggest jumps between consecutive frames inside the preview,
     each shown as the frame before and the frame after;
  3. evenly spaced frames to fill the rest, so slow stretches are covered too.

Those go to Claude with their timestamps, plus a normal screenshot of the screen
as it is now, which is what Claude points at (the timeline, a clip, an effect).

Platform-neutral. A platform that has video review gives its Platform two methods:

  video_window() -> (handle, app name), or (None, why not): the window to record (the one in front)
  video_frame(handle) -> PIL image of that window right now, or None. Called from a worker thread.

and shows the "recording" card through its Nudge (ui.nudge.card / hide), which
every platform has for help mode. Review drives the rest through the controller.
"""
import asyncio
import base64
import io
import os
import threading
import time
from dataclasses import dataclass, field

from . import loop, settings

FPS = 4                     # window grabs per second while recording
MAX_SECONDS = 90            # stop by itself after this long
STORE_LONG_EDGE = 1600      # frames are kept as JPEGs this big
SEND_LONG_EDGE = 1024       # ...and sent this big (after cropping to the preview)
THUMB_W, THUMB_H = 96, 54   # for finding the preview and the cuts
CHANGE = 0.06               # a thumbnail pixel this much brighter/darker = changed
PREVIEW_SHARE = 0.25        # changed in at least this share of the steps = part of the preview
MAX_FRAMES = 12             # frames sent (the full screenshot comes on top)
MAX_CUTS = 5
CUT_MIN = 0.08              # a cut changes the preview at least this much (mean, 0-1)...
CUT_OVER_MEDIAN = 3.0       # ...and this many times more than a typical step

ASK_TEMPLATE = """\
I recorded my screen while I played back my video edit ({seconds:.0f} s, in my editor). Flippy picked these \
frames from the recording, cropped to the video preview{cuts_note}. Each image's label gives its time in the \
recording. The last image is my whole screen right now (it's {w}x{h} pixels); use that one for any [POINT] tags, \
for example to point at a spot on my timeline.

You only see stills: you can't judge smooth motion, timing finer than about a quarter second, or anything in the \
audio, so say so if that's what the question needs. Talk about moments by their time.

{question}

(not a tutorial: just answer and point, no :click)"""


@dataclass
class Frame:
    t: float            # seconds since recording started
    jpeg: bytes         # STORE_LONG_EDGE
    thumb: list         # THUMB_W x THUMB_H grayscale, 0-1
    size: tuple         # (w, h) of the jpeg


@dataclass
class Recording:
    frames: list = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)

    @property
    def seconds(self):
        return self.frames[-1].t if self.frames else 0.0

    def add(self, image):
        """image: a PIL image of the editor's window."""
        from PIL import Image
        im = image.convert("RGB")
        k = STORE_LONG_EDGE / max(im.size)
        if k < 1:
            im = im.resize((round(im.width * k), round(im.height * k)), Image.BILINEAR)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=82)
        thumb = [b / 255 for b in im.convert("L").resize((THUMB_W, THUMB_H), Image.BOX).tobytes()]
        self.frames.append(Frame(time.monotonic() - self.started, buf.getvalue(), thumb, im.size))


# ---- picking frames (pure: tested in tests/test_video.py)

def preview_box(thumbs):
    """(x0, y0, x1, y1) as fractions 0-1 of the part that kept changing, or None if nothing did."""
    if len(thumbs) < 3:
        return None
    counts = [0] * (THUMB_W * THUMB_H)
    for a, b in zip(thumbs, thumbs[1:]):
        for i, (p, q) in enumerate(zip(a, b)):
            if abs(p - q) > CHANGE:
                counts[i] += 1
    need = max(2, PREVIEW_SHARE * (len(thumbs) - 1))
    xs = [i % THUMB_W for i, c in enumerate(counts) if c >= need]
    ys = [i // THUMB_W for i, c in enumerate(counts) if c >= need]
    if len(xs) < 6:  # a few stray pixels (a blinking cursor, a playhead) aren't a preview
        return None
    x0, x1 = max(min(xs) - 1, 0), min(max(xs) + 2, THUMB_W)
    y0, y1 = max(min(ys) - 1, 0), min(max(ys) + 2, THUMB_H)
    return x0 / THUMB_W, y0 / THUMB_H, x1 / THUMB_W, y1 / THUMB_H


def step_scores(thumbs, box=None):
    """Mean change inside box between each frame and the one before it (scores[0] = 0)."""
    x0, y0, x1, y1 = box or (0, 0, 1, 1)
    cols = range(int(x0 * THUMB_W), max(int(x1 * THUMB_W), int(x0 * THUMB_W) + 1))
    rows = range(int(y0 * THUMB_H), max(int(y1 * THUMB_H), int(y0 * THUMB_H) + 1))
    idx = [r * THUMB_W + c for r in rows for c in cols]
    scores = [0.0]
    for a, b in zip(thumbs, thumbs[1:]):
        scores.append(sum(abs(a[i] - b[i]) for i in idx) / len(idx))
    return scores


def find_cuts(scores):
    """Indexes i where frame i starts a new shot: big, local-peak jumps. Biggest first, at most MAX_CUTS."""
    steps = sorted(scores[1:])
    if not steps:
        return []
    median = steps[len(steps) // 2]
    need = max(CUT_MIN, median * CUT_OVER_MEDIAN)
    peaks = [i for i in range(1, len(scores))
             if scores[i] >= need and scores[i] >= scores[i - 1] and (i + 1 >= len(scores) or scores[i] >= scores[i + 1])]
    return sorted(peaks, key=lambda i: -scores[i])[:MAX_CUTS]


def pick(n_frames, cuts, limit=MAX_FRAMES):
    """Frame indexes to send, in time order: around each cut (before, after), then evenly spaced."""
    chosen = set()
    for i in cuts:
        if len(chosen) + 2 > limit:
            break
        chosen.update((i - 1, i))
    if n_frames:
        chosen.update((0, n_frames - 1))
    spare = limit - len(chosen)
    if spare > 0 and n_frames > len(chosen):
        step = n_frames / (spare + 1)
        for k in range(1, spare + 1):
            chosen.add(min(int(k * step), n_frames - 1))
    return sorted(i for i in chosen if 0 <= i < n_frames)[:limit]


# ---- what goes to Claude

def prepare(rec):
    """[(caption, base64 jpeg)] for the frames worth sending, and how many cuts were found."""
    from PIL import Image
    thumbs = [f.thumb for f in rec.frames]
    box = preview_box(thumbs)
    cuts = find_cuts(step_scores(thumbs, box))
    out = []
    for i in pick(len(rec.frames), cuts):
        f = rec.frames[i]
        im = Image.open(io.BytesIO(f.jpeg))
        if box:
            w, h = im.size
            im = im.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)))
        k = SEND_LONG_EDGE / max(im.size)
        if k < 1:
            im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        label = f"t={f.t:.1f}s" + (" (just after a cut)" if i in cuts else "")
        out.append((label, base64.b64encode(buf.getvalue()).decode()))
    return out, len(cuts)


def question(rec, n_cuts, q, screen_size):
    cuts_note = f" ({n_cuts} cut{'s' if n_cuts != 1 else ''} found; each shown just before and after)" if n_cuts else ""
    return ASK_TEMPLATE.format(seconds=rec.seconds, cuts_note=cuts_note, w=screen_size[0], h=screen_size[1],
                               question=q)


async def ask(brain, frames, screen_b64, screen_size, text, on_text=None):
    """Like Brain.ask, with the recording's frames ahead of the screenshot. Same session, so follow-ups work."""
    from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent, TextBlock
    from .brain import BrainError
    if brain.client is None or brain.dirty:
        await brain.reset()
    content = []
    for label, b64 in frames:
        content.append({"type": "text", "text": label})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
    content.append({"type": "text", "text": "my whole screen now:"})
    content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": screen_b64}})
    content.append({"type": "text", "text": text})

    async def messages():
        yield {"type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None}

    await brain.client.query(messages())
    parts = []
    async for msg in brain.client.receive_response():
        if isinstance(msg, StreamEvent):
            ev = msg.event
            if on_text and ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                on_text(ev["delta"]["text"])
        elif isinstance(msg, AssistantMessage):
            brain.last_model = msg.model
            if getattr(msg, "error", None):
                raise BrainError(str(msg.error))
            parts.extend(b.text for b in msg.content if isinstance(b, TextBlock))
        elif isinstance(msg, ResultMessage) and msg.is_error:
            raise BrainError(msg.result or msg.subtype or "unknown error")
    reply = "".join(parts).strip()
    if not reply:
        raise BrainError("empty reply")
    return reply


# ---- the feature: commands, recording thread, asking

class Review:
    """`flippy-ask video` (start / stop and ask), `video start`, `video stop`, `video ask <question>`,
    `video cancel`. flippy: the controller (flippy/daemon.py Flippy)."""

    def __init__(self, flippy):
        self.flippy = flippy
        self.ui = flippy.ui
        self.rec = None             # Recording in progress, or the last one (kept for `video ask`)
        self.recording = False
        self.stop_ev = None
        self.box = None
        self.app_name = None

    def command(self, cmd):
        verb, _, rest = cmd.partition(" ")[2].partition(" ")
        if verb == "":
            return self.stop() if self.recording else self.start()
        if verb == "start":
            return self.start()
        if verb == "stop":
            return self.stop()
        if verb == "cancel":
            return self.cancel()
        if verb == "ask":
            if self.recording:
                self._end()
            return self.ask(rest.strip())
        return "usage: video [start|stop|cancel|ask <question>]"

    def start(self):
        f = self.flippy
        if self.recording:
            return "already recording"
        if f.busy:
            return "busy"
        handle, name = self.ui.video_window()
        if handle is None:
            self._card("Can't record that", name, [("OK", lambda: None)], timeout=6)
            return name
        f.box.hide()
        f.dismiss()
        self.rec, self.recording, self.app_name = Recording(), True, name
        self.stop_ev = threading.Event()
        threading.Thread(target=self._grab, args=(handle, self.rec, self.stop_ev), daemon=True).start()
        self._card(f"Recording {name}", "Play your edit, then stop and ask about it. Only frames in memory, "
                   "never saved.", [("Cancel", self.cancel), ("Stop and ask", self.stop)])
        _event("video_start", app=name)
        return "recording"

    def _grab(self, handle, rec, stop_ev):
        next_t = time.monotonic()
        while not stop_ev.is_set():
            try:
                img = self.ui.video_frame(handle)
            except Exception as e:  # the window went away, a capture failed: stop with what we have
                _log(f"video: grab failed: {e}")
                img = None
            if img is None:
                loop.idle_add(lambda: self.recording and self.stop() and False)
                return
            rec.add(img)
            if rec.seconds >= MAX_SECONDS:
                loop.idle_add(lambda: self.recording and self.stop() and False)
                return
            next_t += 1 / FPS
            stop_ev.wait(max(next_t - time.monotonic(), 0.0))

    def _end(self):
        self.recording = False
        if self.stop_ev:
            self.stop_ev.set()
        self.ui.nudge.hide()
        if self.rec:
            _event("video_stop", seconds=self.rec.seconds, frames=len(self.rec.frames))

    def stop(self):
        """Stop recording and open the question box."""
        if not self.recording:
            return "not recording"
        self._end()
        rec = self.rec
        if len(rec.frames) < 3:
            self.rec = None
            self._card("That was too short", "Play a few seconds of your edit while recording.", [("OK", lambda: None)],
                       timeout=6)
            return "too short"
        self._card("Your edit is ready", f"{rec.seconds:.0f} s recorded. Ask what to check, like “is the cut at "
                   "0:12 clean?” or “does the title stay up long enough?”", [("Discard", self.cancel)])
        self.box = self.ui.input_box(self._submit, self._box_closed)
        self.box.show()
        return "ok"

    def cancel(self):
        if self.recording:
            self._end()
        if self.box:
            self.box.hide()
            self.box = None
        self.rec = None
        self.ui.nudge.hide()
        _event("video_cancel")
        return "ok"

    def _box_closed(self):
        if self.box:
            self.box.hide()
            self.box = None  # keep the recording: `video ask <question>` can still use it
        self.ui.nudge.hide()

    def _submit(self, q):
        if self.box:
            self.box.hide()
            self.box = None
        self.ask(q)

    def ask(self, q):
        f = self.flippy
        if not q:
            return "usage: video ask <question>"
        if not self.rec or len(self.rec.frames) < 3:
            return "nothing recorded: run `flippy-ask video` first"
        if f.busy:
            return "busy"
        self.ui.nudge.hide()
        rec = self.rec
        f.tutorial = False
        f.busy = True
        f.gen += 1
        gen = f.gen
        f._stop_playback()
        f._cancel_fade()
        f.box.hide()
        f.overlay.clear()
        _event("video_ask", question=q)
        loop.timeout_add(self.ui.hide_settle_ms, lambda: self._shoot(rec, q, gen) and False)
        return "ok"

    def _shoot(self, rec, q, gen):
        f = self.flippy

        def shot(path, err):
            if err:
                f._fail(f"couldn't take a screenshot: {err}")
                return
            f.overlay.show_text("looking at your edit…", phase="thinking")
            f.last_ask = time.monotonic()
            f._run(self._go(rec, q, path, gen), f._on_answer, timeout=180)
        f.shooter.take(shot)

    async def _go(self, rec, q, path, gen):
        from .brain import prepare_image
        f = self.flippy
        try:
            b64, img_size, shot_size = await asyncio.to_thread(prepare_image, path, settings.get("claude", "image"))
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        frames, n_cuts = await asyncio.to_thread(prepare, rec)
        loop.idle_add(lambda: f._start_playback(gen, img_size, shot_size) and False)
        raw = await ask(f.brain, frames, b64, img_size, question(rec, n_cuts, q, img_size),
                        on_text=lambda d: loop.idle_add(lambda: f._stream_text(gen, d) and False))
        return raw, gen

    def _card(self, head, detail, buttons, timeout=None):
        self.ui.nudge.card(head, detail, buttons, on_timeout=(lambda: None) if timeout else None,
                           timeout_s=timeout or 15)


def _event(name, **data):
    from .daemon import event
    event(name, **data)


def _log(*a):
    from .daemon import log
    log(*a)
