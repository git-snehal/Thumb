"""Bundled fonts (all SIL OFL, files in assets/fonts). Add one by dropping woff2 files there and listing it here."""
from __future__ import annotations

from dataclasses import dataclass

LATIN = ("U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,"
         "U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD")
LATIN_EXT = ("U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,"
             "U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF")


@dataclass(frozen=True)
class FontSpec:
    key: str
    label: str
    family: str
    file_stem: str            # fontsource file prefix, e.g. "bebas-neue"
    weights: tuple[int, ...]
    subsets: tuple[str, ...] = ("latin", "latin-ext")
    body_safe: bool = False   # True: also used for descriptions; False: titles/buttons only
    title_scale: float = 1.0  # compensates for wide/narrow letterforms so titles keep fitting
    tracking: str = "-.02em"
    caps: bool = True         # False for script fonts: capitals would be unreadable

    @property
    def css_family(self) -> str:
        return f"'{self.family}'"


FONTS: dict[str, FontSpec] = {f.key: f for f in [
    FontSpec("poppins", "Poppins", "Poppins", "", (300, 400, 500, 700), (), True, 1.0),
    FontSpec("montserrat", "Montserrat", "Montserrat", "montserrat", (400, 500, 700), body_safe=True, title_scale=0.95),
    FontSpec("inter", "Inter", "Inter", "inter", (400, 500, 700), body_safe=True, title_scale=1.0),
    FontSpec("oswald", "Oswald", "Oswald", "oswald", (400, 500, 700), title_scale=1.2, tracking=".01em"),
    FontSpec("bebas", "Bebas Neue", "Bebas Neue", "bebas-neue", (400,), title_scale=1.32, tracking=".02em"),
    FontSpec("anton", "Anton", "Anton", "anton", (400,), title_scale=1.18, tracking=".01em"),
    FontSpec("playfair", "Playfair Display", "Playfair Display", "playfair-display", (400, 500, 700), title_scale=1.0, tracking="-.01em"),
    FontSpec("cinzel", "Cinzel", "Cinzel", "cinzel", (400, 500, 700), title_scale=0.88, tracking=".01em"),
    FontSpec("orbitron", "Orbitron", "Orbitron", "orbitron", (400, 700), ("latin",), title_scale=0.8, tracking=".01em"),
    FontSpec("bangers", "Bangers", "Bangers", "bangers", (400,), title_scale=1.1, tracking=".02em"),
    FontSpec("pacifico", "Pacifico", "Pacifico", "pacifico", (400,), title_scale=0.82, tracking="0", caps=False),
]}
DEFAULT_FONT = "poppins"


def get(key: str | None) -> FontSpec:
    return FONTS.get(key or "", FONTS[DEFAULT_FONT])


def font_css(font: FontSpec, host: str) -> str:
    """@font-face rules for the chosen font (Poppins is always declared by the base template)."""
    if not font.file_stem:
        return ""
    ranges = {"latin": LATIN, "latin-ext": LATIN_EXT}
    out = []
    for w in font.weights:
        for sub in font.subsets:
            out.append(
                f"@font-face{{font-family:'{font.family}';font-weight:{w};font-style:normal;"
                f"src:url('{host}fonts/{font.file_stem}-{sub}-{w}-normal.woff2') format('woff2');"
                f"unicode-range:{ranges[sub]};}}"
            )
    return "\n".join(out)
