"""Optional owner watermark, applied to every image the bot sends.

Two independent layers, both off unless configured:

* WATERMARK_TEXT: a faint diagonal pattern of that text across the picture (visible).
* WATERMARK_KEY: an invisible keyed mark spread over the whole picture. It survives JPEG recompression (what Telegram
  does when someone forwards a photo). `python -m bot.watermark verify image.jpg KEY` tells you whether a picture
  came from your bot.

It's a deterrent and a way to prove origin, not unbreakable protection: resizing, cropping or heavy filtering destroys
the invisible mark (the visible text stays). Check suspicious files at the size the bot sent them.
"""
from __future__ import annotations

import hashlib
import io
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BLOCK = 4            # the invisible pattern is made of 4x4 pixel blocks, so it survives JPEG better than per-pixel noise
STRENGTH = 3.0       # luminance units (0-255): invisible to the eye, strong enough to detect
THRESHOLD = 6.0      # z-score above which "this is ours" (chance of a false positive is about 1 in a billion)


def _pattern(key: str, h: int, w: int) -> np.ndarray:
    seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    bh, bw = -(-h // BLOCK), -(-w // BLOCK)
    blocks = rng.choice((-1.0, 1.0), size=(bh, bw))
    return np.kron(blocks, np.ones((BLOCK, BLOCK)))[:h, :w]


def embed(img: Image.Image, key: str) -> Image.Image:
    rgb = img.convert("RGB")
    arr = np.asarray(rgb, dtype=np.float32)
    pat = _pattern(key, arr.shape[0], arr.shape[1])[..., None]
    out = np.clip(arr + STRENGTH * pat, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGB")


def detect(img: Image.Image, key: str) -> float:
    """z-score of the keyed pattern in this picture (about 0 when it isn't there, 10+ when it is)."""
    gray = img.convert("L")
    arr = np.asarray(gray, dtype=np.float32)
    hp = arr - np.asarray(gray.filter(ImageFilter.GaussianBlur(BLOCK * 2)), dtype=np.float32)   # drop the picture itself
    pat = _pattern(key, *arr.shape)
    n_blocks = (arr.shape[0] / BLOCK) * (arr.shape[1] / BLOCK)
    corr = float((hp * pat).mean())
    noise = float(hp.std()) / np.sqrt(n_blocks)
    return corr / noise if noise else 0.0


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def visible(img: Image.Image, text: str, opacity: float = 0.07) -> Image.Image:
    """Tile `text` diagonally over the picture at low opacity."""
    base = img.convert("RGBA")
    w, h = base.size
    size = max(14, h // 22)
    font = _font(size)
    tile = Image.new("RGBA", (int(size * (len(text) * 0.62 + 4)), size * 4), (0, 0, 0, 0))
    ImageDraw.Draw(tile).text((size, size), text, font=font, fill=(255, 255, 255, int(255 * opacity * 3)))
    tile = tile.rotate(24, expand=True, resample=Image.BICUBIC)
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    for y in range(-tile.height, h + tile.height, tile.height):
        for x in range(-tile.width, w + tile.width, tile.width):
            layer.paste(tile, (x, y), tile)
    return Image.alpha_composite(base, layer).convert("RGB")


def apply(data: bytes, fmt: str, text: str = "", key: str = "") -> bytes:
    """Return `data` (a JPEG or PNG) with the configured watermark layers applied. Unchanged when both are empty."""
    if not (text or key):
        return data
    img = Image.open(io.BytesIO(data))
    img.load()
    if text:
        img = visible(img, text)
    if key:
        img = embed(img, key)
    out = io.BytesIO()
    if fmt.lower() in ("jpeg", "jpg"):
        img.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    else:
        img.save(out, "PNG")
    return out.getvalue()


def _cli(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] != "verify":
        print("usage: python -m bot.watermark verify <image> <WATERMARK_KEY>")
        return 2
    z = detect(Image.open(argv[1]), argv[2])
    print(f"score {z:.1f}: " + ("this picture carries your mark." if z >= THRESHOLD else "no mark found."))
    return 0 if z >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
