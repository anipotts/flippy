"""Screenshot preparation and coordinates shared by tutoring and desktop tools."""
import base64
import hashlib
import io
import math
from dataclasses import dataclass, field

from PIL import Image

from .point import pick_target_size


@dataclass(frozen=True)
class ScreenFrame:
    jpeg: str
    size: tuple[int, int]
    logical_size: tuple[float, float]
    target: tuple | None = None
    fingerprint: str = ""
    original_size: tuple[int, int] = (0, 0)
    pixels: bytes = field(default=b"", repr=False, compare=False)

    def to_logical(self, x, y, *, clamp=False):
        w, h = self.size
        if clamp:
            x, y = max(0, min(x, w - 1)), max(0, min(y, h - 1))
        elif not (0 <= x < w and 0 <= y < h):
            raise ValueError("point is outside the screenshot")
        return x * self.logical_size[0] / w, y * self.logical_size[1] / h

    def substantial_change(self, other, name, args):
        """Compare the intended input region, tolerating caret-scale pixel changes.

        Click/scroll inspect a 96-image-pixel square; drag inspects both ends.
        Keyboard/text inspect the foreground window. RGB deltas >=24 covering
        1% of a local region or 2% of a window, or mean max-channel delta >=8,
        count as substantial. Small consequential edits can be missed: this is
        a usability guard, not semantic verification or permission to act.
        """
        if self.target != other.target or self.size != other.size or self.original_size != other.original_size:
            return True
        if not self.pixels or not other.pixels:
            # Compatibility fixtures and older adapters cannot relax an exact check.
            return not self.fingerprint or self.fingerprint != other.fingerprint
        try:
            if name in ("click", "scroll", "drag"):
                points = [(args["x"], args["y"])]
                if name == "drag":
                    points.append((args["to_x"], args["to_y"]))
                boxes = []
                for x, y in points:
                    if type(x) is not int or type(y) is not int or not (0 <= x < self.size[0] and 0 <= y < self.size[1]):
                        return True
                    boxes.append((max(0, x - 48), max(0, y - 48),
                                  min(self.size[0], x + 48), min(self.size[1], y + 48)))
                share, sample_edge = 0.01, 96
            elif name in ("type", "key"):
                if not self.target or len(self.target) < 4 or not self.target[3]:
                    return True
                x, y, width, height = self.target[3]
                sx, sy = self.size[0] / self.logical_size[0], self.size[1] / self.logical_size[1]
                boxes = [(max(0, math.floor(x * sx)), max(0, math.floor(y * sy)),
                          min(self.size[0], math.ceil((x + width) * sx)),
                          min(self.size[1], math.ceil((y + height) * sy)))]
                share, sample_edge = 0.02, 256
            else:
                return True
            before = Image.frombytes("RGB", self.size, self.pixels)
            after = Image.frombytes("RGB", other.size, other.pixels)
            for box in boxes:
                if box[2] <= box[0] or box[3] <= box[1]:
                    return True
                a, b = before.crop(box), after.crop(box)
                a.thumbnail((sample_edge, sample_edge), Image.Resampling.BILINEAR)
                b.thumbnail((sample_edge, sample_edge), Image.Resampling.BILINEAR)
                first, second = a.tobytes(), b.tobytes()
                deltas = [max(abs(first[i + c] - second[i + c]) for c in range(3))
                          for i in range(0, len(first), 3)]
                if (sum(delta >= 24 for delta in deltas) / len(deltas) >= share
                        or sum(deltas) / len(deltas) >= 8):
                    return True
            return False
        except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
            return True

    def content(self):
        w, h = self.size
        return [{"type": "text", "text": f"Screenshot: {w}x{h} pixels; origin top-left."},
                {"type": "image", "data": self.jpeg, "mimeType": "image/jpeg"}]


def prepare_frame(path, long_edge=1920, *, logical_size=None, target=None):
    """Hash decoded full-resolution pixels, then prepare the model-visible JPEG."""
    with Image.open(path) as source:
        rgb = source.convert("RGB")
        original = rgb.size
        digest = hashlib.sha256()
        digest.update(f"{original[0]}x{original[1]}:".encode("ascii"))
        digest.update(rgb.tobytes())
        size = pick_target_size(*original, long_edge or max(original))
        small = rgb.resize(size, Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="JPEG", quality=85)
    return ScreenFrame(base64.b64encode(buf.getvalue()).decode(), size,
                       logical_size or original, target, digest.hexdigest(), original, small.tobytes())


def prepare_image(path, long_edge=1920):
    """Compatibility for callers outside the controller."""
    frame = prepare_frame(path, long_edge)
    return frame.jpeg, frame.size, frame.original_size
