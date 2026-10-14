"""Screenshot preparation and coordinates shared by tutoring and desktop tools."""
import base64
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


def prepare_frame(path, long_edge=1920, *, logical_size=None):
    """The model-visible JPEG of a screenshot."""
    with Image.open(path) as source:
        rgb = source.convert("RGB")
        original = rgb.size
        size = pick_target_size(*original, long_edge or max(original))
        small = rgb.resize(size, Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="JPEG", quality=85)
    return ScreenFrame(base64.b64encode(buf.getvalue()).decode(), size,
                       logical_size or original, original_size=original)
