"""Prepare a user-supplied background image."""
from __future__ import annotations

import io

from PIL import Image, ImageOps

MAX_PIXELS = 60_000_000


def prepare_background(raw: bytes) -> tuple[bytes, bool]:
    """Returns (JPEG bytes, is_wide). Raises ValueError for unreadable or tiny images."""
    img = Image.open(io.BytesIO(raw))
    img.load()
    if img.width * img.height > MAX_PIXELS:
        raise ValueError("Image is too large.")
    img = ImageOps.exif_transpose(img).convert("RGB")
    if min(img.size) < 200:
        raise ValueError("Image is too small.")
    img.thumbnail((1920, 1920))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90, optimize=True)
    return out.getvalue(), img.width / img.height >= 1.4
