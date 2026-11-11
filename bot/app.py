"""Shared application state passed to every handler."""
from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

from aiogram.exceptions import TelegramBadRequest

from dataclasses import replace

from . import artsources, icons, schemes, watermark
from .anilist import AniList, split_special, split_title
from .assets import AnimeCache
from .config import Config
from .fanart import prepare_character
from .grid import compose_grid
from .guard import RateLimited, RateLimiter  # noqa: F401  (RateLimited is re-exported for the handlers)
from .registry import TemplateSpec
from .render import Renderer
from .store import Store
from .style import Style

log = logging.getLogger(__name__)
T = TypeVar("T")

class NeedCharacter(Exception):
    """The special design was requested but the user hasn't uploaded a character for this anime."""


BUSY: set[tuple[int, int]] = set()   # (chat, message) currently being re-rendered


@dataclass
class App:
    cfg: Config
    anilist: AniList
    cache: AnimeCache
    renderer: Renderer
    templates: list[TemplateSpec]
    store: Store
    limiter: RateLimiter = field(default_factory=RateLimiter)

    @property
    def tmdb(self):
        return self.cache.tmdb

    def spec(self, key: str) -> TemplateSpec | None:
        return next((t for t in self.templates if t.key == key), None)

    async def style_for(self, uid: int) -> Style:
        """Merge the user's saved choices with the bot-wide defaults from settings.py."""
        s = await self.store.get(uid)
        if s.brand_off:
            text, logo = "", None
        else:
            logo = None
            if s.logo_path and Path(s.logo_path).is_file():
                logo = "data:image/png;base64," + base64.b64encode(Path(s.logo_path).read_bytes()).decode()
            text = s.brand_text if s.brand_text is not None else ("" if logo else self.cfg.brand_name)
        return Style(text, logo, s.position or self.cfg.brand_position, s.font or "poppins",
                     logo_position=s.logo_position or self.cfg.logo_position,
                     special_defaults=self.cfg.special_defaults,        # the owner's built-in branding is fixed
                     wm_opacity=self.cfg.wm_opacity, boxes_opacity=self.cfg.boxes_opacity)

    async def art_for(self, uid: int, anime: dict, hd: bool = False) -> tuple[str | None, bool]:
        """The main artwork: the user's own image, else a TMDB backdrop, else None (= AniList cover)."""
        choice = await self.store.get_art(uid, anime["id"])
        if choice["path"]:
            raw = await asyncio.to_thread(Path(choice["path"]).read_bytes)
            return "data:image/jpeg;base64," + base64.b64encode(raw).decode(), choice["wide"]
        urls = anime.get("tmdb_urls") or []
        if urls and choice["idx"] >= 0:
            url = urls[choice["idx"] % len(urls)]
            uri = await self.cache.tmdb_image(url, hd=hd)
            if uri:
                return uri, url not in (anime.get("portrait_urls") or [])      # Jikan/Kitsu posters are portrait
        if choice["idx"] == -2 and anime.get("banner"):          # the person picked AniList's wide banner
            return anime["banner"], True
        return None, False

    async def art_label(self, uid: int, anime: dict) -> tuple[str, bool, int]:
        """(what is being used, has custom image, number of TMDB images) for the Background panel."""
        choice = await self.store.get_art(uid, anime["id"])
        n = len(anime.get("tmdb_urls") or [])
        src = "TMDB" if anime.get("source") == "tmdb" else "AniList"
        cover_word, banner_word = ("poster", "backdrop") if src == "TMDB" else ("cover", "banner")
        if choice["path"]:
            return "your image", True, n
        if n and choice["idx"] >= 0:
            url = anime["tmdb_urls"][choice["idx"] % n]
            return f"{artsources.source_name(url)} image {choice['idx'] % n + 1} of {n}", False, n
        if choice["idx"] == -2 and anime.get("banner"):
            return f"{src} {banner_word}", False, n
        return f"{src} {cover_word}", False, n

    async def next_images(self, uid: int, anime: dict) -> list[str]:
        """Two DIFFERENT pictures for the 'Next' cards of the special design: the TMDB backdrops after the chosen
        one, or (AniList chosen / no TMDB) AniList episode thumbnails, then its banner, then its cover."""
        idx = (await self.store.get_art(uid, anime["id"]))["idx"]
        portrait = anime.get("portrait_urls") or []
        urls = [u for u in (anime.get("tmdb_urls") or []) if u not in portrait]     # the cards are wide: skip posters
        out: list[str] = []
        if urls and idx >= 0:
            n = len(urls)
            order = [(idx + k) % n for k in (1, 2)] if n >= 3 else [i for i in range(n) if i != idx % n]
            for i in dict.fromkeys(order):
                uri = await self.cache.tmdb_image(urls[i])
                if uri:
                    out.append(uri)
        for uri in (*anime.get("thumbs", []), anime.get("banner"), anime.get("cover")):
            if len(out) >= 2:
                break
            if uri:
                out.append(uri)
        return out[:2]

    async def render(self, media_id: int, spec: TemplateSpec, uid: int, fmt: str = "jpeg", *, scale: float = 1.0,
                     hd: bool = False, cost: int = 1) -> tuple[dict, bytes]:
        """Render one design for one person. hd=True gives a 2560x1440 picture built from full-size TMDB art.
        cost is what this counts as against the rate limit (0 = already counted by the caller)."""
        if cost:
            self.limiter.check(uid, cost)
        anime = await self.cache.get(media_id)
        style = await self.style_for(uid)
        prefs = await self.store.get(uid)
        anime = with_title_lang(anime, prefs.title_lang)
        if prefs.title_logo == "off":
            anime = {**anime, "title_logo": None}
        if not spec.special:
            art, wide = await self.art_for(uid, anime, hd=hd)
            anime = {**anime, "art": art or anime["cover"], "art_wide": wide}
        anime = apply_edits(anime, await self.store.get_edits(uid, media_id))
        if spec.special:
            ch = await self.store.get_character(uid, media_id)
            if not ch:
                raise NeedCharacter()
            s = prefs
            src = "data:image/png;base64," + base64.b64encode(Path(ch["path"]).read_bytes()).decode()
            style = replace(style, scheme=schemes.resolve(s.scheme, anime["accent"]),
                            char={"src": src, "dx": ch["dx"], "scale": ch["scale"]})
            anime = {**anime, "ttl": await self.store.get_title(uid, media_id),
                     "next_imgs": await self.next_images(uid, anime)}
        data = await self.renderer.render(spec.file, anime, spec.variant, fmt=fmt, style=style,
                                          scale=2.0 if hd else scale)
        if scale >= 1.0:                       # previews for the design grid are marked once, on the finished grid
            data = await self.mark(data, fmt)
        return anime, data

    async def mark(self, data: bytes, fmt: str) -> bytes:
        """Apply the owner's watermark (WATERMARK_TEXT / WATERMARK_KEY) when one is configured."""
        if not (self.cfg.watermark_text or self.cfg.watermark_key):
            return data
        try:
            return await asyncio.to_thread(watermark.apply, data, fmt, self.cfg.watermark_text, self.cfg.watermark_key)
        except Exception:
            log.exception("watermark failed; sending the picture without it")
            return data

    # ------------------------------------------------------------------ fanart.tv characters (special design)
    async def character_candidates(self, anime: dict) -> list[str]:
        fanart = self.cache.fanart
        if not (fanart and fanart.enabled):
            return []
        try:
            return await fanart.character_urls(anime)
        except Exception as e:
            log.warning("fanart character lookup failed: %s", e)
            return []

    async def pick_character(self, uid: int, media_id: int, start: int = 0) -> int | None:
        """Download the first usable transparent fanart.tv image from candidate `start` on (wrapping round), save it as
        this person's character for this anime and return its index. None when there is nothing usable."""
        anime = await self.cache.get(media_id)
        urls = await self.character_candidates(anime)
        for step in range(len(urls)):
            i = (start + step) % len(urls)
            raw = await self.cache.fanart.fetch(urls[i])
            png = await asyncio.to_thread(prepare_character, raw) if raw else None
            if png:
                await self.store.save_character(uid, media_id, png, src_idx=i)
                return i
        return None

    async def preview_grid(self, uid: int, media_id: int) -> tuple[bytes, list[TemplateSpec]]:
        """One image with every design (the special one only if this person has a character for the anime)."""
        self.limiter.check(uid, 3)                      # a grid is ~13 renders but costs just 3 'points'

        async def one(spec: TemplateSpec):
            try:
                return spec, (await self.render(media_id, spec, uid, "jpeg", scale=0.5, cost=0))[1]
            except NeedCharacter:
                return None

        results = [r for r in await asyncio.gather(*(one(s) for s in self.templates)) if r]
        anime = await self.cache.get(media_id)
        grid = await asyncio.to_thread(compose_grid, [(s.label.replace("✨ ", ""), img) for s, img in results], anime["title"])
        return await self.mark(grid, "jpeg"), [s for s, _ in results]


_TITLE_KEYS = {"english": "title_english", "romaji": "title_romaji", "native": "title_native"}


def with_title_lang(anime: dict, lang: str | None) -> dict:
    """Show the title in the person's chosen language. 'auto' (or a language this title doesn't have) keeps the default."""
    key = _TITLE_KEYS.get(lang or "")
    wanted = (anime.get(key) or "").strip() if key else ""
    if not wanted or wanted == anime.get("title"):
        return anime
    a, b = split_title(wanted)
    big, small = split_special(wanted)
    return {**anime, "title": wanted, "title_a": a, "title_b": b, "title_big": big, "title_small": small}


def apply_edits(anime: dict, edits: dict) -> dict:
    """Overlay the person's corrected text on top of AniList's (synopsis, genres, season line, episode label)."""
    if not edits:
        return anime
    out = dict(anime)
    if "synopsis" in edits:
        out["description"] = edits["synopsis"]
    if "genres" in edits:
        genres = [g.strip() for g in edits["genres"].split(",") if g.strip()][:4]
        out["genres4"], out["genres"] = genres, genres[:3]
    if "season_line" in edits:
        out["season_line"] = edits["season_line"]
    if "episodes_label" in edits:
        out["episodes_label"] = edits["episodes_label"]
    if "badges" in edits:
        out["badges"] = [b.strip() for b in edits["badges"].split(",") if b.strip()][:4]
    return out


async def guard_icons(make: Callable[[], Awaitable[T]]) -> T:
    """Run a send/edit that includes animated icons. If Telegram rejects the request while icons
    are configured, turn icons off for good and retry once with plain emoji.
    `make` must build its keyboard inside so the retry picks up the change."""
    try:
        return await make()
    except TelegramBadRequest as e:
        if "not modified" in str(e) or not icons.any_configured():
            raise
        log.warning("Telegram rejected custom emoji icons (%s). Falling back to plain emoji.", e)
        icons.disable()
        return await make()
