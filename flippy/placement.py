"""Where a docked answer goes: the spot on screen where it blocks the least (#23).

When you're learning something on screen, Claude marks what you need to keep seeing ([LEARN:...], flippy/point.py)
and the answer docks away from it. The spot is scored on the screenshot: covering Claude's box costs the most,
then the text you're working in and the rest of its window (the platform's work_area), then busy pixels (text,
icons, edges), so blank margins, empty panels, the desktop and apps in the background win. Spots near the screen's edges are preferred over
the middle. Pure: no windows, so it's tested directly (tests/test_dock_pin.py).
"""
from PIL import Image, ImageFilter

COLUMNS = 64          # the detail map's resolution across the screen
STEP = 24             # candidate spots, in logical px
GAP = 16              # from the screen's edges
KEEP, WORK, WINDOW, BUSY, MIDDLE = 8.0, 3.0, 1.5, 1.0, 0.15  # what covering each costs, per share of the card


class Detail:
    """How much is going on in each part of the screenshot (0 = flat color, 1 = dense text or edges)."""

    def __init__(self, values, columns, rows, logical_size):
        self.columns, self.rows = columns, rows
        self.cell_w, self.cell_h = logical_size[0] / columns, logical_size[1] / rows
        self.sums = [[0.0] * (columns + 1) for _ in range(rows + 1)]  # summed-area table
        for r in range(rows):
            run = 0.0
            for c in range(columns):
                run += values[r * columns + c]
                self.sums[r + 1][c + 1] = self.sums[r][c + 1] + run

    @classmethod
    def from_frame(cls, frame):
        """From a flippy.frames.ScreenFrame (its downscaled pixels, the copy sent to Claude)."""
        if not frame.pixels:
            return None
        w, h = frame.size
        rows = max(1, round(COLUMNS * h / w))
        edges = Image.frombytes("RGB", frame.size, frame.pixels).convert("L").filter(ImageFilter.FIND_EDGES)
        small = edges.resize((COLUMNS, rows), Image.Resampling.BOX)
        return cls([min(v / 64, 1.0) for v in small.tobytes()], COLUMNS, rows, frame.logical_size)

    def mean(self, rect):
        x, y, w, h = rect
        c0, c1 = _clamp(int(x / self.cell_w), self.columns), _clamp(int((x + w) / self.cell_w) + 1, self.columns)
        r0, r1 = _clamp(int(y / self.cell_h), self.rows), _clamp(int((y + h) / self.cell_h) + 1, self.rows)
        cells = (c1 - c0) * (r1 - r0)
        if not cells:
            return 0.0
        s = self.sums
        return (s[r1][c1] - s[r0][c1] - s[r1][c0] + s[r0][c0]) / cells


def _clamp(v, hi):
    return max(0, min(v, hi))


def overlap(a, b):
    """Area two (x, y, w, h) rects share."""
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(w, 0) * max(h, 0)


def best_spot(W, H, cw, ch, *, keep=None, work=None, window=None, detail=None, top=GAP, bottom=GAP):
    """(x, y) of a cw x ch card on a W x H screen that blocks the least. top/bottom: space kept clear (the menu bar,
    the Dock)."""
    xs = _positions(GAP, W - cw - GAP)
    ys = _positions(top, H - ch - bottom)
    area = cw * ch

    def cost(x, y):
        rect = (x, y, cw, ch)
        c = 0.0
        if keep:
            c += KEEP * overlap(rect, keep) / area
        if work:
            c += WORK * overlap(rect, work) / area
        if window:
            c += WINDOW * overlap(rect, window) / area
        if detail:
            c += BUSY * detail.mean(rect)
        edge = min(x, W - cw - x, y, H - ch - y)  # how far it floats from the nearest edge
        return c + MIDDLE * edge / max(min(W, H) / 2, 1)

    return min(((x, y) for y in ys for x in xs), key=lambda p: (cost(*p), -p[0], p[1]))  # ties: right, then top


def _positions(lo, hi):
    if hi <= lo:
        return [max(lo, 0)]
    out = list(range(int(lo), int(hi), STEP))
    return out + [hi] if out[-1] != hi else out
