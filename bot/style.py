from __future__ import annotations

from dataclasses import dataclass

POSITIONS = {
    "tl": "Top left",
    "tr": "Top right",
    "bl": "Bottom left",
    "br": "Bottom right",
}


@dataclass(frozen=True)
class Style:
    """Everything a user can customise about how a banner looks."""
    brand_text: str = ""
    logo: str | None = None   # data URI of the user's logo
    position: str = "tr"      # where the brand TEXT goes (one of POSITIONS)
    font: str = "poppins"
    scheme: dict | None = None      # special design colours {a, b, glow, label}
    char: dict | None = None        # special design character {src, dx, scale}
    logo_position: str = "tl"       # the logo can sit in a different corner from the text
    special_defaults: bool = True   # built-in OD3N watermark / credit in the special design
    wm_opacity: float = 0.11
    boxes_opacity: float = 1.0      # the five side boxes (1 = pure white)
