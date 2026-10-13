"""POINT tag protocol (from Clicky, MIT: see THIRD_PARTY_NOTICES.md) and image<->screen coordinate mapping."""
import re
from dataclasses import dataclass

# Clicky's tag, anywhere in the text (inline pointing: one tag right after each thing mentioned). Flippy adds an
# optional ":click" flag after the label: a tutorial step the user has to do (click that thing) before the
# walkthrough goes on.
TAG_RE = re.compile(r"\[POINT:(?:none|(\d+)\s*,\s*(\d+)(?::([^\]:\s][^\]:]*?))?(:click)?(?::screen(\d+))?)\]")
TAG_PREFIX = "[POINT:"
PUNCT = ".,;:!?"

# Flippy's: at the very start of a reply, "they're learning something on screen; this box is what they need to keep
# seeing" (x1,y1,x2,y2 in screenshot pixels, optional). The answer then docks where it blocks the least
# (flippy/placement.py).
LEARN_RE = re.compile(r"\s*\[LEARN(?::\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*)?\]")
LEARN_PREFIX = "[LEARN"

# Screenshot size sent to Claude. Clicky used 1024x768/1280x800/1366x768 for older models;
# with Opus 5.x, pointing was equally accurate at full res in our tests (~2px), and the
# bigger image makes small tray icons recognizable. Costs ~2x the image tokens of 1366.
TARGET_LONG_EDGE = 1920


@dataclass
class Point:
    x: int  # in screenshot-image pixels
    y: int
    label: str
    action: bool = False  # ":click": the user has to click it before the walkthrough goes on


def _point(m):
    """The Point a TAG_RE match names, or None for [POINT:none]."""
    if m.group(1) is None:
        return None
    return Point(int(m.group(1)), int(m.group(2)), (m.group(3) or "").strip(), bool(m.group(4)))


def match_tag(text: str, i: int):
    """At text[i] == '[': return (end, Point|None) for a complete tag, "wait" if it may be a
    tag still streaming in, or None if it's just a bracket."""
    m = TAG_RE.match(text, i)
    if m:
        return m.end(), _point(m)
    rest = text[i:]
    if "]" not in rest and (TAG_PREFIX.startswith(rest) or rest.startswith(TAG_PREFIX)):
        return "wait"
    return None


@dataclass
class Learn:
    box: "tuple[int, int, int, int] | None"  # x1, y1, x2, y2 in screenshot-image pixels


def split_learn(raw: str, done: bool):
    """(Learn, the rest) for a reply starting with a LEARN tag; ("wait", "") while one may still be streaming in;
    else (None, raw)."""
    m = LEARN_RE.match(raw)
    if m:
        box = tuple(int(g) for g in m.groups()) if m.group(1) else None
        return Learn(box), raw[m.end():]
    start = raw.lstrip()
    if not done and "]" not in start and (LEARN_PREFIX.startswith(start) or start.startswith(LEARN_PREFIX)):
        return "wait", ""
    return None, raw


@dataclass
class Segment:
    text: str             # the words for this step (tags removed)
    point: "Point | None"  # where the hand goes for this step (None = stay put)
    complete: bool        # False while the step is still streaming in


def segments(raw: str, done: bool) -> list[Segment]:
    """Split a (possibly still streaming) reply into steps, one per POINT tag.

    Each tag ends a step: the text since the previous tag is what's said while
    pointing there. Text after the last tag becomes a final step without a point.
    """
    segs: list[Segment] = []
    pos = 0
    _, raw = split_learn(raw, done)
    for m in TAG_RE.finditer(raw):
        pt = _point(m)
        end = m.end()
        while end < len(raw) and raw[end] in PUNCT:  # "...Files [POINT..]." -> the "." belongs here
            end += 1
        text = tidy(raw[pos:m.start()] + raw[m.end():end])
        if text or pt:
            segs.append(Segment(text, pt, True))
        pos = end
    tail = raw[pos:]
    if not done:
        i = tail.rfind("[")
        if i >= 0 and match_tag(tail, i) == "wait":
            tail = tail[:i]  # don't show half a tag
    tail = tidy(tail.lstrip(PUNCT + " "))
    if tail:
        segs.append(Segment(tail, None, done))
    return segs


def tidy(text: str) -> str:
    """Clean up the gaps left where inline tags were removed."""
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([,.;:!?)])", r"\1", text)
    return text.strip()


def pick_target_size(w: int, h: int, long_edge: int = TARGET_LONG_EDGE) -> tuple[int, int]:
    """Scale so the long edge is long_edge (never upscale), keeping the exact aspect."""
    k = min(long_edge / max(w, h), 1.0)
    return round(w * k), round(h * k)


def image_to_logical(pt: Point, img_size: tuple[int, int], shot_size: tuple[int, int],
                     scale: float) -> tuple[float, float]:
    """Map a point in the downscaled image to logical (layer-shell) pixels.

    The portal screenshot is in physical pixels; layer-shell surfaces are logical,
    so divide by the monitor scale after scaling up to screenshot size.
    """
    img_w, img_h = img_size
    shot_w, shot_h = shot_size
    x = min(max(pt.x, 0), img_w - 1) * (shot_w / img_w) / scale
    y = min(max(pt.y, 0), img_h - 1) * (shot_h / img_h) / scale
    return x, y
