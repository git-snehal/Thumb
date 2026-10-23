"""Background colour schemes for the Special Design."""
from __future__ import annotations

import colorsys
import re

# key: (label, dot, top colour, bottom colour, glow/accent colour)
PRESETS: dict[str, tuple[str, str, str, str, str]] = {
    "sakura":   ("Sakura",   "🌸", "#b84f9f", "#5a2380", "#ff6fd0"),
    "ocean":    ("Ocean",    "🔵", "#0b3b9c", "#5b2a9a", "#8b5cf6"),
    "sunset":   ("Sunset",   "🟠", "#6b1535", "#c2410c", "#fb923c"),
    "emerald":  ("Emerald",  "🟢", "#043d36", "#16756b", "#34d399"),
    "crimson":  ("Crimson",  "🔴", "#3d0a14", "#9b1c31", "#f43f5e"),
    "violet":   ("Violet",   "🟣", "#2a1065", "#a21caf", "#d946ef"),
    "midnight": ("Midnight", "⚫", "#0b1220", "#1f2a44", "#60a5fa"),
    "gold":     ("Gold",     "🟡", "#3b2a06", "#8a5a12", "#fbbf24"),
}
AUTO = "auto"
DEFAULT = "sakura"
_HEX = re.compile(r"#?([0-9a-fA-F]{6})")


def _hex_to_hsv(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hsv(r, g, b)


def _hsv_to_hex(h: float, s: float, v: float) -> str:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0, min(s, 1)), max(0, min(v, 1)))
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _dark_enough(hex_color: str, max_lum: float = 0.24) -> str:
    """Make a colour dark enough for white text. Pale colours gain saturation first, so a pale pink
    becomes a dusty rose instead of a flat grey."""
    h, s, v = _hex_to_hsv(hex_color)
    out = hex_color
    for _ in range(60):
        out = _hsv_to_hex(h, s, v)
        if _luminance(out) <= max_lum:
            break
        if 0.08 <= s < 0.5:                 # has a hue worth keeping; greys just get darker
            s = min(0.5, s + 0.08)
        else:
            v -= 0.03
    return out


MAX_COLORS = 4


def parse_custom(text: str) -> str | None:
    """'#112233 #445566 #778899' -> '#112233,#445566,#778899' (1 to 4 colours, top to bottom; extras are ignored)."""
    found = ["#" + m.lower() for m in _HEX.findall(text)]
    return ",".join(found[:MAX_COLORS]) if found else None


def count_colors(text: str) -> int:
    return len(_HEX.findall(text))


def _derive(a: str, accent_hint: str | None = None) -> dict:
    h, s, v = _hex_to_hsv(a)
    top = _hsv_to_hex(h, max(s, .55), min(max(v, .35), .6))
    bottom = _hsv_to_hex(h + 0.09, max(s, .6), min(max(v * .8, .28), .5))
    glow = accent_hint or _hsv_to_hex(h, .55, .98)
    return {"a": top, "b": bottom, "glow": glow}


def resolve(value: str | None, cover_accent: str = "#7c5cff") -> dict:
    """value: preset key, 'auto', or custom '#aaaaaa[,#bbbbbb]'. Returns {a, b, glow, label}."""
    value = value or DEFAULT
    if value in PRESETS:
        label, _, a, b, glow = PRESETS[value]
        return {"a": a, "b": b, "glow": glow, "label": label}
    if value == AUTO:
        d = _derive(cover_accent)
        return {**d, "label": "Auto (from cover)"}
    parts = [p for p in value.split(",") if _HEX.fullmatch(p)][:MAX_COLORS]
    if len(parts) >= 3:                       # 3 or 4 colours: an even top-to-bottom gradient through every colour
        stops = [_dark_enough(p) for p in parts]
        vividest = max(parts, key=lambda p: _hex_to_hsv(p)[1])
        glow = _hsv_to_hex(_hex_to_hsv(vividest)[0], .55, .98)
        return {"a": stops[0], "b": stops[-1], "glow": glow, "stops": stops, "label": f"Custom ({len(parts)} colors)"}
    if parts:
        a = _dark_enough(parts[0])
        if len(parts) == 2:
            b = _dark_enough(parts[1])
            glow = _hsv_to_hex(_hex_to_hsv(parts[1])[0], .55, .98)
            return {"a": a, "b": b, "glow": glow, "label": "Custom"}
        d = _derive(parts[0])
        return {**d, "a": a, "label": "Custom"}
    return resolve(DEFAULT, cover_accent)


def from_image(raw: bytes, n: int = 3) -> str | None:
    """Pick up to `n` characteristic colours from a character image (transparent areas, near-white, near-black and
    grey pixels are ignored because they say nothing about the character). Returns '#a,#b,#c' lightest first, or
    None if the picture has no usable colour."""
    import io

    import numpy as np
    from PIL import Image

    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    img.thumbnail((160, 160))
    arr = np.asarray(img).astype(float) / 255.0
    px = arr[arr[..., 3] > 0.8][:, :3]
    if len(px) < 60:
        return None
    mx, mn = px.max(axis=1), px.min(axis=1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-9), 0)
    for min_sat in (0.28, 0.14):                              # fall back to paler pictures
        keep = (sat >= min_sat) & (mx >= 0.2) & (mx <= 0.97)
        if keep.mean() >= 0.04:
            break
    else:
        return None
    sel = (px[keep] * 255).astype("uint8")
    pal_img = Image.fromarray(sel.reshape(-1, 1, 3), "RGB").quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = pal_img.getpalette()
    counted = sorted(pal_img.getcolors(), reverse=True)        # [(pixels, palette index), ...]
    cands = []
    for count, idx in counted:
        r, g, b = palette[idx * 3: idx * 3 + 3]
        h, s, v = _hex_to_hsv("#{:02x}{:02x}{:02x}".format(r, g, b))
        cands.append((count * (0.35 + s), h, s, v))
    cands.sort(reverse=True)
    chosen: list[tuple[float, float, float]] = []
    for _, h, s, v in cands:
        far = all(min(abs(h - ch), 1 - abs(h - ch)) > 0.07 or abs(v - cv) > 0.3 for ch, _, cv in chosen)
        if far:
            chosen.append((h, s, v))
        if len(chosen) == n:
            break
    if not chosen:
        return None
    if len(chosen) == 1:                                       # one-colour character: add a neighbouring hue
        h, s, v = chosen[0]
        chosen.append(((h + 0.09) % 1.0, s, max(v * 0.7, 0.3)))
    chosen.sort(key=lambda c: c[2], reverse=True)               # lighter at the top, darker lower
    return ",".join(_hsv_to_hex(h, s, v) for h, s, v in chosen)


def accent_from_image(raw: bytes) -> str | None:
    """The most colourful characteristic colour of a picture (for titles whose source gives no cover colour)."""
    value = from_image(raw, 3)
    if not value:
        return None
    return max(value.split(","), key=lambda c: _hex_to_hsv(c)[1])
