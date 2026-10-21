"""Contact sheet: the same anime in every design, numbered, so people can pick without tapping through."""
from __future__ import annotations

import io
from math import ceil

from PIL import Image, ImageDraw, ImageFont

from .config import ROOT

FONT = ROOT / "assets" / "fonts" / "Poppins-Bold.ttf"
REG = ROOT / "assets" / "fonts" / "Poppins-Medium.ttf"


def compose_grid(tiles: list[tuple[str, bytes]], title: str, cols: int = 3, tile=(640, 360),
                 gap: int = 18, label_h: int = 46, head: int = 84) -> bytes:
    """tiles: [(label, jpeg/png bytes), ...] in display order. Returns a JPEG."""
    tw, th = tile
    rows = ceil(len(tiles) / cols)
    width = cols * tw + (cols + 1) * gap
    height = head + rows * (th + label_h + gap) + gap
    canvas = Image.new("RGB", (width, height), (19, 17, 30))
    d = ImageDraw.Draw(canvas)
    big, mid, small = (ImageFont.truetype(str(FONT), s) for s in (34, 22, 22))
    d.text((gap + 4, 16), title[:60], font=big, fill=(255, 255, 255))
    d.text((gap + 4, 56), "Tap a number under the picture to use that design", font=ImageFont.truetype(str(REG), 18), fill=(170, 165, 195))
    for i, (label, raw) in enumerate(tiles):
        col, row = i % cols, i // cols
        x = gap + col * (tw + gap)
        y = head + gap + row * (th + label_h + gap)
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        if img.size != tile:
            img = img.resize(tile, Image.LANCZOS)
        canvas.paste(img, (x, y))
        d.rounded_rectangle([x, y, x + tw - 1, y + th - 1], radius=2, outline=(70, 66, 100), width=2)
        badge = 46
        d.rounded_rectangle([x + 10, y + 10, x + 10 + badge, y + 10 + badge - 8], radius=12, fill=(124, 92, 255))
        num = str(i + 1)
        w = d.textlength(num, font=mid)
        d.text((x + 10 + (badge - w) / 2, y + 12), num, font=mid, fill=(255, 255, 255))
        d.text((x + 4, y + th + 10), label[:34], font=small, fill=(225, 222, 240))
    out = io.BytesIO()
    canvas.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()
