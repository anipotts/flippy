"""Screenshot preparation and coordinates shared by tutoring and desktop tools."""
import base64
import hashlib
import io
from dataclasses import dataclass

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

    def to_logical(self, x, y, *, clamp=False):
        w, h = self.size
        if clamp:
            x, y = max(0, min(x, w - 1)), max(0, min(y, h - 1))
        elif not (0 <= x < w and 0 <= y < h):
            raise ValueError("point is outside the screenshot")
        return x * self.logical_size[0] / w, y * self.logical_size[1] / h

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
                       logical_size or original, target, digest.hexdigest(), original)


def prepare_image(path, long_edge=1920):
    """Compatibility for callers outside the controller."""
    frame = prepare_frame(path, long_edge)
    return frame.jpeg, frame.size, frame.original_size
