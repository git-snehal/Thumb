"""Turn an uploaded character image into a cropped transparent PNG.

  transparent  already has an alpha channel -> used as is
  ai           opaque upload, background removed with rembg's anime model (if installed)
  flat         opaque upload on a plain background, removed with a flood fill
  opaque       couldn't remove the background -> kept as is (will look boxed)
"""
from __future__ import annotations

import io
import logging

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

log = logging.getLogger(__name__)
_session = None
MAX_PIXELS = 40_000_000


def has_transparency(img: Image.Image) -> bool:
    alpha = np.asarray(img.getchannel("A"))
    return float((alpha < 250).mean()) > 0.01


def _looks_cut(img: Image.Image) -> bool:
    """A usable cutout removes some background but not (almost) everything."""
    transparent = float((np.asarray(img.getchannel("A")) < 40).mean())
    return 0.03 < transparent < 0.92


def remove_with_ai(img: Image.Image) -> Image.Image | None:
    try:
        from rembg import new_session, remove
    except ImportError:
        return None
    global _session
    try:
        if _session is None:
            _session = new_session("isnet-anime")
        out = remove(img, session=_session).convert("RGBA")
        return out if _looks_cut(out) else None
    except Exception:
        log.exception("AI background removal failed")
        return None


def remove_flat_background(img: Image.Image, tol: int = 22) -> Image.Image | None:
    """Flood-fill from the borders. Only works when the background is one plain colour."""
    rgb = img.convert("RGB")
    arr = np.asarray(rgb).astype(int)
    h, w, _ = arr.shape
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    ref = np.median(border, axis=0)
    near = (np.abs(border - ref).max(axis=1) <= tol).mean()
    if near < 0.85:
        return None                      # busy / gradient background: don't guess

    marker = (255, 0, 255)
    work = rgb.copy()
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
             (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
    for s in seeds:
        px = np.array(work.getpixel(s))
        if np.abs(px - ref).max() <= tol and work.getpixel(s) != marker:
            ImageDraw.floodfill(work, s, marker, thresh=tol)
    bg = (np.asarray(work) == np.array(marker)).all(axis=2)
    if not (0.03 < bg.mean() < 0.92):
        return None
    alpha = Image.fromarray(np.where(bg, 0, 255).astype("uint8"), "L")
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.9))   # trim halo, soften edge
    out = img.convert("RGBA")
    out.putalpha(alpha)
    return out


def prepare(raw: bytes, use_ai: bool = True) -> tuple[bytes, str]:
    """Returns (png bytes, mode). Raises ValueError for unreadable / oversized images."""
    img = Image.open(io.BytesIO(raw))
    img.load()
    if img.width * img.height > MAX_PIXELS:
        raise ValueError("Image is too large.")
    img = img.convert("RGBA")
    img.thumbnail((1800, 1800))

    if has_transparency(img):
        mode = "transparent"
    else:
        cut = remove_with_ai(img) if use_ai else None
        mode = "ai"
        if cut is None:
            cut, mode = remove_flat_background(img), "flat"
        if cut is None:
            mode = "opaque"
        else:
            img = cut

    if mode != "opaque":                 # trim empty margins so every character is sized consistently
        bbox = img.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
        if bbox:
            pad = 4
            img = img.crop((max(bbox[0] - pad, 0), max(bbox[1] - pad, 0),
                            min(bbox[2] + pad, img.width), min(bbox[3] + pad, img.height)))
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue(), mode


def warm_up() -> None:
    """Load the AI model once at startup (downloads ~180 MB the first time). Safe if rembg isn't installed."""
    try:
        from rembg import new_session
    except ImportError:
        log.info("rembg not installed: uploads on plain backgrounds still work, AI cutout is off.")
        return
    global _session
    try:
        _session = new_session("isnet-anime")
        log.info("Background-removal model ready.")
    except Exception:
        log.exception("Couldn't load the background-removal model")
