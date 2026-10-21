"""Render every template to PNG/JPEG without Telegram.

    python -m scripts.preview --sample          # placeholder art, works offline
    python -m scripts.preview --id 163134       # real data from AniList
    python -m scripts.preview --id 163134 --only poster3
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter

from bot.anilist import AniList, readable_on, vivid
from bot.assets import AnimeCache, inline_images
from bot.tmdb import TMDB
from bot.config import ROOT, brand_name
from bot import schemes
from bot.registry import load_templates
from bot.render import Renderer
from bot.style import Style


def _uri(img: Image.Image, fmt: str = "JPEG") -> str:
    buf = io.BytesIO()
    if fmt == "PNG":
        img.save(buf, "PNG")
    else:
        img.convert("RGB").save(buf, "JPEG", quality=88)
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()


def _art(w: int, h: int, c1: str, c2: str, seed: int) -> Image.Image:
    """Abstract placeholder 'key art' so layouts can be checked offline."""
    import random

    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h), c1)
    px = img.load()
    a = tuple(int(c1[i : i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i : i + 2], 16) for i in (1, 3, 5))
    for y in range(h):
        t = y / h
        for x in range(w):
            u = (t * 0.8 + x / w * 0.2)
            px[x, y] = tuple(int(a[i] * (1 - u) + b[i] * u) for i in range(3))
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(14):
        r = rnd.randint(w // 10, w // 3)
        cx, cy = rnd.randint(0, w), rnd.randint(0, h)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, rnd.randint(8, 34)))
    for i in range(3):  # three stand-in "characters"
        cx = int(w * (0.28 + i * 0.22))
        top = int(h * (0.28 + (i % 2) * 0.06))
        d.ellipse([cx - w // 14, top, cx + w // 14, top + w // 7], fill=(250, 226, 205, 235))
        d.rounded_rectangle([cx - w // 11, top + w // 8, cx + w // 11, h], radius=w // 12,
                            fill=(40 + i * 30, 50, 90 + i * 25, 240))
    return img.filter(ImageFilter.GaussianBlur(1.2))


def sample_character() -> str:
    """A transparent stand-in 'character' (head, hair, body, sword) so the special design can be checked offline."""
    W, H = 520, 900
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(250, 140), (130, 220), (110, 520), (170, 600), (190, 300)], fill=(90, 150, 255, 255))      # hair back
    d.polygon([(270, 140), (390, 220), (410, 540), (350, 620), (330, 300)], fill=(90, 150, 255, 255))
    d.ellipse([190, 120, 330, 290], fill=(250, 220, 200, 255))                                              # face
    d.polygon([(180, 190), (260, 110), (340, 190), (300, 150), (220, 150)], fill=(120, 180, 255, 255))     # fringe
    d.ellipse([220, 190, 245, 220], fill=(40, 70, 150, 255)); d.ellipse([280, 190, 305, 220], fill=(40, 70, 150, 255))
    d.rounded_rectangle([170, 290, 350, 620], radius=60, fill=(220, 60, 90, 255))                           # dress
    d.polygon([(170, 560), (350, 560), (420, 900), (100, 900)], fill=(240, 240, 250, 255))                  # skirt
    d.rectangle([436, 100, 446, 860], fill=(210, 190, 90, 255)); d.polygon([(441, 40), (470, 110), (412, 110)], fill=(230, 70, 70, 255))
    return _uri(img.filter(ImageFilter.GaussianBlur(0.6)), "PNG")


def sample_anime() -> dict:
    accent = "#5b6cff"
    chars = []
    for i, (n, v) in enumerate([("Alisa Mikhailovna Kujou", "Sayumi Watabe"),
                                ("Masachika Kuze", "Yoshitaka Yamaya"),
                                ("Yuki Suou", "Konomi Inohara")]):
        chars.append({"name": n, "role": "MAIN", "va_name": v,
                      "image": _uri(_art(160, 160, "#e8a3b8", "#7a5cff", i)),
                      "va_image": _uri(_art(160, 160, "#9fd3ff", "#2b3a67", i + 9))})
    return {
        "id": 0, "url": None,
        "title": "Alya Sometimes Hides Her Feelings in Russian",
        "title_a": "Alya Sometimes Hides", "title_b": "Her Feelings in Russian",
        "title_big": "Russian", "title_small": "Alya Sometimes Hides Her Feelings in",
        "title_native": "時々ボソッとロシア語でデレる隣のアーリャさん",
        "description": "Alya is a transfer student enjoying popularity at her new high school, often sporting a "
        "cold shoulder while earning high marks in class. She ignores her nerdy classmate, Kuze Masachika, "
        "except for when she blurts out a flirtatious line to him in Russian. Little does she know, Kuze "
        "understands Russian, though he pretends not to. Let's see where this wacky love story takes them!",
        "format": "TV", "status": "Finished", "season": "Summer", "year": 2024, "episodes": 12, "duration": 24,
        "score10": 8.3, "stars5": 4.15, "star_pct": 83.0,
        "genres": ["Comedy", "Romance", "Slice of Life"], "genres4": ["Slice of Life", "Comedy", "Drama", "Romance"], "studio": "Doga Kobo",
        "accent": accent, "accent_fg": readable_on(accent),
        "accent_vivid": vivid(accent), "accent_vivid_fg": readable_on(vivid(accent)),
        "banner": _uri(_art(1900, 400, "#1d2347", "#e08aa6", 3)),
        "cover": _uri(_art(460, 650, "#243064", "#f0a1b5", 5)),
        "thumbs": [_uri(_art(320, 180, "#1d2347", c, s)) for s, c in enumerate(["#e08aa6", "#7aa2ff", "#f3c07a"])],
        "characters": chars,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--id", type=int)
    ap.add_argument("--only")
    ap.add_argument("--brand", default=brand_name(), help="brand text")
    ap.add_argument("--logo", help="path to a PNG logo")
    ap.add_argument("--pos", default="tr", choices=["tl", "tr", "bl", "br"], help="brand text corner")
    ap.add_argument("--logo-pos", default="tl", choices=["tl", "tr", "bl", "br"], help="logo corner")
    ap.add_argument("--no-defaults", action="store_true", help="hide the built-in OD3N special-design assets")
    ap.add_argument("--font", default="poppins")
    ap.add_argument("--scheme", default="ocean", help="preset key, auto, or #hex[,#hex]")
    ap.add_argument("--char", help="path to a transparent character PNG (special design)")
    ap.add_argument("--tmdb", default="", help="TMDB API key: use HD backdrop art for --id")
    ap.add_argument("--art-index", type=int, default=0, help="which TMDB backdrop (0 = best)")
    ap.add_argument("--art-image", help="path to your own background image")
    ap.add_argument("--wide", action="store_true", help="with --sample: use wide placeholder art to preview full-bleed layouts")
    ap.add_argument("--out", default=str(ROOT / "preview"))
    args = ap.parse_args()
    if not (args.sample or args.id):
        ap.error("pass --sample or --id <anilist id>")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.sample:
        anime = sample_anime()
    else:
        async with httpx.AsyncClient(headers={"User-Agent": "anime-thumb-bot-preview"}) as http:
            al = AniList(http)
            cache = AnimeCache(al, http, 60, tmdb=TMDB(http, args.tmdb))
            anime = await cache.get(args.id)
            urls = anime.get("tmdb_urls") or []
            print(f"TMDB: {len(urls)} backdrop(s) found" if args.tmdb else "TMDB: no key given, using AniList art")
            if urls:
                uri = await cache.tmdb_image(urls[args.art_index % len(urls)])
                if uri:
                    anime = {**anime, "art": uri, "art_wide": True}
    if args.art_image:
        im = Image.open(args.art_image)
        anime = {**anime, "art": _uri(im.convert("RGB")), "art_wide": im.width / im.height >= 1.4}
    elif args.sample and args.wide:
        anime = {**anime, "art": _uri(_art(1920, 1080, "#1d2347", "#e08aa6", 11)), "art_wide": True}

    logo = None
    if args.logo:
        logo = "data:image/png;base64," + base64.b64encode(Path(args.logo).read_bytes()).decode()
    if args.char:
        char_src = "data:image/png;base64," + base64.b64encode(Path(args.char).read_bytes()).decode()
    else:
        char_src = sample_character()
    style = Style(args.brand, logo, args.pos, args.font,
                  schemes.resolve(args.scheme, anime["accent"]), {"src": char_src, "dx": 0, "scale": 1.0},
                  logo_position=args.logo_pos, special_defaults=not args.no_defaults)
    r = Renderer(ROOT / "templates", ROOT / "assets")
    try:
        for t in load_templates(ROOT / "templates.json"):
            if args.only and args.only not in t.key:
                continue
            data = await r.render(t.file, anime, t.variant, fmt="png", style=style)
            (out / f"{t.key}.png").write_bytes(data)
            print("rendered", t.key, f"{len(data) // 1024} KB")
    finally:
        await r.close()


if __name__ == "__main__":
    asyncio.run(main())
