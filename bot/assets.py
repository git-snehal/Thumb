"""Fetch remote images once, inline them as data URIs, and cache the prepared anime."""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections import OrderedDict

import httpx

from . import schemes
from .anilist import AniList, SourceError, readable_on, vivid
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


async def _data_uri(client: httpx.AsyncClient, url: str | None, max_width: int | None = None) -> str | None:
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
    if max_width:
        shrunk = await asyncio.to_thread(_shrink, content, max_width)
        if shrunk:
            content, mime = shrunk
    return f"data:{mime};base64,{base64.b64encode(content).decode()}"


async def inline_images(client: httpx.AsyncClient, anime: dict) -> dict:
    """Replace every *_url with an embedded data URI so rendering needs no network."""
    chars = anime["characters"]
    jobs = [
        _data_uri(client, anime["banner_url"]),
        _data_uri(client, anime["cover_url"]),
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

    def __init__(self, anilist: AniList, http: httpx.AsyncClient, ttl: int, size: int = 64, tmdb=None):
        self.anilist, self.http, self.ttl, self.size, self.tmdb = anilist, http, ttl, size, tmdb
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
        prepared = await inline_images(self.http, raw)
        if prepared.get("needs_accent"):
            await self._accent_from_poster(prepared)
        prepared["tmdb_urls"] = await self._tmdb_paths(prepared)
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

    async def _tmdb_paths(self, anime: dict) -> list[str]:
        """Backdrop paths from TMDB, or [] for any reason at all (no key, no match, network error)."""
        if not (self.tmdb and self.tmdb.enabled):
            return []
        try:
            return await asyncio.wait_for(self.tmdb.backdrops(anime), 20)
        except Exception as e:           # TMDB is a bonus; it must never break a banner
            log.warning("TMDB lookup failed for %r: %s", anime.get("title"), e)
            return []

    async def tmdb_image(self, path: str, hd: bool = False) -> str | None:
        """One TMDB backdrop as a data URI (cached). hd=True fetches TMDB's full-size file (limited to 2560px wide)."""
        cache = self._hd if hd else self._imgs
        if path in cache:
            cache.move_to_end(path)
            return cache[path]
        if not self.tmdb:
            return None
        uri = await _data_uri(self.http, self.tmdb.image_url(path, "original" if hd else "w1280"), 2560 if hd else None)
        if uri:
            cache[path] = uri
            while len(cache) > (6 if hd else 40):
                cache.popitem(last=False)
        return uri
