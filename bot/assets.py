"""Fetch remote images once, inline them as data URIs, and cache the prepared anime."""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections import OrderedDict

import httpx

from . import artsources, schemes
from .anilist import AniList, SourceError, readable_on, vivid
from .fanart import prepare_logo
from .ids import is_tmdb

log = logging.getLogger(__name__)


def _shrink(raw: bytes, max_width: int) -> tuple[bytes, str] | None:
    """Downscale a big image (TMDB 'original' can be 4K+) to max_width as JPEG. None if it can't be read."""
    import io

    from PIL import Image

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        if img.width <= max_width:
            return None            # already small enough: use the bytes as they are
        img = img.convert("RGB")
        img = img.resize((max_width, round(img.height * max_width / img.width)), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, "JPEG", quality=90, optimize=True)
        return out.getvalue(), "image/jpeg"
    except Exception:
        return None


def upscale_small(raw: bytes, min_height: int = 1350, max_factor: float = 3.0) -> tuple[bytes, str] | None:
    """Enlarge a small picture (e.g. an AniList cover) before it is embedded, so the 2x HD export isn't blocky.
    LANCZOS plus a light unsharp mask. It can't invent detail, it only makes the enlargement cleaner than the
    browser's own scaling. None when the picture is already big enough (or can't be read)."""
    import io

    from PIL import Image, ImageFilter

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        if img.height >= min_height or img.height < 64:
            return None
        factor = min(max_factor, min_height / img.height)
        img = img.convert("RGB").resize((round(img.width * factor), round(img.height * factor)), Image.LANCZOS)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.4, percent=55, threshold=3))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=92, optimize=True)
        return out.getvalue(), "image/jpeg"
    except Exception:
        return None


async def _data_uri(client: httpx.AsyncClient, url: str | None, max_width: int | None = None,
                    upscale: bool = False) -> str | None:
    if not url:
        return None
    try:
        r = await client.get(url, timeout=30 if max_width else 15, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    mime = r.headers.get("content-type", "image/jpeg").split(";")[0]
    if not mime.startswith("image/"):
        return None
    content = r.content
    shrunk = await asyncio.to_thread(_shrink, content, max_width) if max_width else None
    if shrunk:
        content, mime = shrunk
    elif upscale:
        bigger = await asyncio.to_thread(upscale_small, content)
        if bigger:
            content, mime = bigger
    return f"data:{mime};base64,{base64.b64encode(content).decode()}"


async def inline_images(client: httpx.AsyncClient, anime: dict, upscale: bool = True) -> dict:
    """Replace every *_url with an embedded data URI so rendering needs no network."""
    chars = anime["characters"]
    jobs = [
        _data_uri(client, anime["banner_url"]),
        _data_uri(client, anime["cover_url"], upscale=upscale),
        *[_data_uri(client, u) for u in anime["thumb_urls"]],
        *[_data_uri(client, c["image_url"]) for c in chars],
        *[_data_uri(client, c["va_image_url"]) for c in chars],
    ]
    out = await asyncio.gather(*jobs)
    n = len(anime["thumb_urls"])
    banner, cover, thumbs = out[0], out[1], [t for t in out[2 : 2 + n] if t]
    char_imgs = out[2 + n : 2 + n + len(chars)]
    va_imgs = out[2 + n + len(chars) :]

    prepared = {k: v for k, v in anime.items() if not k.endswith("_url")}
    prepared["banner"] = banner
    prepared["cover"] = cover or banner
    prepared["thumbs"] = thumbs
    prepared["characters"] = [
        {**{k: v for k, v in c.items() if not k.endswith("_url")}, "image": ci, "va_image": vi}
        for c, ci, vi in zip(chars, char_imgs, va_imgs)
    ]
    return prepared


class AnimeCache:
    """Small TTL + LRU cache of fully prepared anime dicts, keyed by AniList id."""

    def __init__(self, anilist: AniList, http: httpx.AsyncClient, ttl: int, size: int = 64, tmdb=None,
                 fanart=None, extra_art: bool = True, upscale: bool = True, title_logos: bool = True):
        self.anilist, self.http, self.ttl, self.size, self.tmdb = anilist, http, ttl, size, tmdb
        self.fanart, self.extra_art, self.upscale, self.title_logos = fanart, extra_art, upscale, title_logos
        self._imgs: OrderedDict[str, str] = OrderedDict()      # TMDB image path -> data URI
        self._hd: OrderedDict[str, str] = OrderedDict()        # the same, full-size (for the 2x export)
        self._data: OrderedDict[int, tuple[float, dict]] = OrderedDict()
        self._locks: dict[int, asyncio.Lock] = {}

    async def get(self, media_id: int) -> dict:
        hit = self._data.get(media_id)
        if hit and time.time() - hit[0] < self.ttl:
            self._data.move_to_end(media_id)
            return hit[1]
        lock = self._locks.setdefault(media_id, asyncio.Lock())
        async with lock:  # collapse concurrent fetches of the same title
            hit = self._data.get(media_id)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]
            try:
                prepared = await self._fetch(media_id)
            except Exception as e:
                if hit:    # the source is down but we have an older copy: keep working with it for a couple of minutes
                    log.warning("Refreshing title %s failed (%s); serving the cached copy.", media_id, e)
                    self._data[media_id] = (time.time() - self.ttl + 120, hit[1])
                    return hit[1]
                raise
            self._data[media_id] = (time.time(), prepared)
            while len(self._data) > self.size:
                self._data.popitem(last=False)
            return prepared

    async def _fetch(self, media_id: int) -> dict:
        """Fetch one title from its source (AniList, or TMDB for negative ids) and prepare it for rendering."""
        if is_tmdb(media_id):
            if not (self.tmdb and self.tmdb.enabled):
                raise SourceError("TMDB isn't set up on this bot, so I can't open that title.")
            raw = await self.tmdb.media(media_id)
        else:
            raw = await self.anilist.media(media_id)
        prepared = await inline_images(self.http, raw, upscale=self.upscale)
        if prepared.get("needs_accent"):
            await self._accent_from_poster(prepared)
        (paths, logos), extras = await asyncio.gather(self._tmdb_images(prepared), self._extra_art(prepared))
        # "tmdb_urls" is the list of alternative pictures: TMDB backdrop paths, then full urls of portrait posters
        prepared["tmdb_urls"] = [*paths, *extras]
        prepared["portrait_urls"] = extras
        prepared["title_logo"] = await self._title_logo(prepared, logos) if self.title_logos else None
        return prepared

    async def _accent_from_poster(self, anime: dict) -> None:
        """TMDB gives no cover colour (AniList does), so take the poster's most colourful characteristic colour."""
        anime.pop("needs_accent", None)
        uri = anime.get("cover")
        if not uri:
            return
        try:
            raw = base64.b64decode(uri.split(",", 1)[1])
            color = await asyncio.to_thread(schemes.accent_from_image, raw)
        except Exception:
            return
        if color:
            anime.update(accent=color, accent_fg=readable_on(color), accent_vivid=vivid(color),
                         accent_vivid_fg=readable_on(vivid(color)))

    async def _tmdb_images(self, anime: dict) -> tuple[list[str], list[str]]:
        """(backdrop paths, logo paths) from TMDB, or ([], []) for any reason at all (no key, no match, network error)."""
        if not (self.tmdb and self.tmdb.enabled):
            return [], []
        try:
            return await asyncio.wait_for(self.tmdb.images(anime), 20)
        except Exception as e:           # TMDB is a bonus; it must never break a banner
            log.warning("TMDB lookup failed for %r: %s", anime.get("title"), e)
            return [], []

    async def _tmdb_paths(self, anime: dict) -> list[str]:
        """Just the TMDB backdrop paths (kept for callers and tests that only want those)."""
        return (await self._tmdb_images(anime))[0]

    async def _extra_art(self, anime: dict) -> list[str]:
        if not self.extra_art:
            return []
        try:
            return await asyncio.wait_for(artsources.extra_posters(self.http, anime), 15)
        except Exception as e:
            log.info("Extra art lookup failed for %r: %s", anime.get("title"), e)
            return []

    async def _title_logo(self, anime: dict, tmdb_logos: list[str]) -> str | None:
        """The show's real title logo as a data URI (fanart.tv first, then TMDB), or None to use plain text."""
        try:
            return await asyncio.wait_for(self._title_logo_inner(anime, tmdb_logos), 25)
        except Exception as e:
            log.info("Title logo lookup failed for %r: %s", anime.get("title"), e)
            return None

    async def _title_logo_inner(self, anime: dict, tmdb_logos: list[str]) -> str | None:
        urls: list[str] = []
        if self.fanart and self.fanart.enabled:
            urls += await self.fanart.logo_urls(anime)
        if self.tmdb:
            urls += [self.tmdb.image_url(p, "w500") for p in tmdb_logos[:2]]
        for url in urls[:4]:
            try:
                r = await self.http.get(url, timeout=20, follow_redirects=True)
                r.raise_for_status()
            except httpx.HTTPError:
                continue
            png = await asyncio.to_thread(prepare_logo, r.content)
            if png:
                return "data:image/png;base64," + base64.b64encode(png).decode()
        return None

    async def tmdb_image(self, path: str, hd: bool = False) -> str | None:
        """One TMDB backdrop as a data URI (cached). hd=True fetches TMDB's full-size file (limited to 2560px wide)."""
        cache = self._hd if hd else self._imgs
        if path in cache:
            cache.move_to_end(path)
            return cache[path]
        if not self.tmdb and not path.startswith("http"):
            return None
        if path.startswith("http"):                      # a portrait poster from Jikan / Kitsu: already a full url
            url = path
        else:
            url = self.tmdb.image_url(path, "original" if hd else "w1280")
        portrait = path.startswith("http")
        uri = await _data_uri(self.http, url, 2560 if hd else (1600 if portrait else None),
                              upscale=portrait and self.upscale)
        if uri:
            cache[path] = uri
            while len(cache) > (6 if hd else 40):
                cache.popitem(last=False)
        return uri
