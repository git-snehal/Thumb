"""fanart.tv: transparent character art and title logos.

fanart.tv is keyed by TheTVDB id (shows) or TMDB id (movies). AniList ids are translated with the community
Fribb/anime-lists file (downloaded once a week and kept in data/), and TMDB's external_ids is the fallback.
Everything here is a bonus: no key, no match or a network error just returns empty lists and the bot carries on.

Needs a free personal API key (FANART_API_KEY). Attribution: images from fanart.tv.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import time
from collections import OrderedDict
from pathlib import Path

import httpx
from PIL import Image

log = logging.getLogger(__name__)

API = "https://webservice.fanart.tv/v3"
MAP_URL = "https://raw.githubusercontent.com/Fribb/anime-lists/master/anime-list-full.json"
MAP_MAX_AGE = 7 * 86400
RECORD_TTL = 6 * 3600

# fanart.tv image kinds, best first
SHOW_CHARACTERS = ("characterart", "hdclearart", "clearart")
SHOW_LOGOS = ("hdtvlogo", "clearlogo")
MOVIE_CHARACTERS = ("hdmovieclearart", "movieart")
MOVIE_LOGOS = ("hdmovielogo", "movielogo")


def pick_urls(record: dict, kinds: tuple[str, ...], prefer_lang: tuple[str, ...] = ("en", "ja", "", "00")) -> list[str]:
    """Image urls of the given kinds: preferred language first, then most liked. Duplicates removed."""
    items: list[dict] = []
    for kind in kinds:
        items += [i for i in (record.get(kind) or []) if i.get("url")]

    def lang_rank(i: dict) -> int:
        lang = (i.get("lang") or "").lower()
        return prefer_lang.index(lang) if lang in prefer_lang else len(prefer_lang)

    items.sort(key=lambda i: (lang_rank(i), -int(i.get("likes") or 0)))
    return list(dict.fromkeys(i["url"] for i in items))


def has_transparency(img: Image.Image) -> bool:
    """True when the picture really has see-through areas (not just an alpha channel full of 255)."""
    if img.mode not in ("RGBA", "LA"):
        return False
    alpha = img.getchannel("A")
    low, _high = alpha.getextrema()
    if low > 200:
        return False
    hist = alpha.histogram()
    clear = sum(hist[:32])
    return clear > alpha.width * alpha.height * 0.05


def prepare_character(raw: bytes, min_height: int = 1100, max_height: int = 2000, max_factor: float = 2.0) -> bytes | None:
    """PNG bytes ready to use as the special design's character, or None when it isn't a transparent image.
    Small art is enlarged (up to max_factor) so it doesn't look soft; huge art is shrunk to keep the database small."""
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        img = img.convert("RGBA")
    except Exception:
        return None
    if not has_transparency(img):
        return None
    bbox = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if bbox:
        img = img.crop(bbox)
    if img.height < min_height:
        factor = min(max_factor, min_height / img.height)
        img = img.resize((round(img.width * factor), round(img.height * factor)), Image.LANCZOS)
    elif img.height > max_height:
        img = img.resize((round(img.width * max_height / img.height), max_height), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def prepare_logo(raw: bytes, max_w: int = 900, max_h: int = 360) -> bytes | None:
    """A title logo as a cropped, size-limited PNG, or None when it can't be used."""
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        img = img.convert("RGBA")
    except Exception:
        return None
    bbox = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if not bbox:
        return None
    img = img.crop(bbox)
    if img.width < 40 or img.height < 12:
        return None
    img.thumbnail((max_w, max_h), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


class Fanart:
    def __init__(self, http: httpx.AsyncClient, key: str, tmdb, data_dir: Path):
        self.http = http
        self.key = (key or "").strip()
        self.tmdb = tmdb
        self.map_file = Path(data_dir) / "anilist_tvdb.json"
        self._map: dict[int, int] | None = None
        self._map_lock = asyncio.Lock()
        self._records: OrderedDict[int, tuple[float, dict, float]] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    # ------------------------------------------------------------------ id translation
    async def _anilist_to_tvdb(self) -> dict[int, int]:
        async with self._map_lock:
            if self._map is not None:
                return self._map
            fresh = self.map_file.is_file() and time.time() - self.map_file.stat().st_mtime < MAP_MAX_AGE
            if fresh:
                try:
                    self._map = {int(k): int(v) for k, v in json.loads(self.map_file.read_text()).items()}
                    return self._map
                except Exception:
                    pass
            try:
                r = await self.http.get(MAP_URL, timeout=90, follow_redirects=True)
                r.raise_for_status()
                self._map = {int(x["anilist_id"]): int(x["tvdb_id"]) for x in r.json()
                             if x.get("anilist_id") and x.get("tvdb_id")}
                self.map_file.parent.mkdir(parents=True, exist_ok=True)
                self.map_file.write_text(json.dumps(self._map))
                log.info("anilist->tvdb map loaded: %d entries", len(self._map))
            except Exception as e:
                log.warning("anilist->tvdb map download failed: %s", e)
                if self.map_file.is_file():                  # an old copy is better than nothing
                    try:
                        self._map = {int(k): int(v) for k, v in json.loads(self.map_file.read_text()).items()}
                    except Exception:
                        pass
            return self._map if self._map is not None else {}

    async def _tvdb_from_tmdb(self, kind: str, tmdb_id: int) -> int | None:
        if kind != "tv" or not (self.tmdb and self.tmdb.enabled):
            return None
        data = await self.tmdb._get(f"/tv/{tmdb_id}/external_ids")
        return int(data["tvdb_id"]) if data.get("tvdb_id") else None

    async def _lookup_key(self, anime: dict) -> tuple[str, int, str] | None:
        """('tv', tvdb_id, how) or ('movies', tmdb_id, how) for this title, or None."""
        ref = anime.get("tmdb_ref")
        if ref:
            kind, tid = ref
            if kind == "movie":
                return "movies", int(tid), "TMDB movie id"
            tvdb = await self._tvdb_from_tmdb("tv", int(tid))
            return ("tv", tvdb, "TMDB external ids") if tvdb else None
        aid = anime.get("id")
        tvdb = (await self._anilist_to_tvdb()).get(int(aid)) if aid else None
        if tvdb:
            return "tv", tvdb, "anime-lists map"
        if self.tmdb and self.tmdb.enabled:                  # not in the map: find it on TMDB instead
            found = await self.tmdb.find(anime)
            if found:
                kind, tid, _ = found
                if kind == "movie":
                    return "movies", int(tid), "TMDB search (movie)"
                tvdb = await self._tvdb_from_tmdb("tv", int(tid))
                if tvdb:
                    return "tv", tvdb, "TMDB search + external ids"
        return None

    # ------------------------------------------------------------------ fanart.tv records
    async def record(self, anime: dict) -> tuple[str, dict]:
        """('tv'|'movies', the fanart.tv record). The record also carries _status / _why / _id / _how for diagnostics.
        Only real answers (200 and 404) are remembered; a hiccup or a rejected key is retried on the next request."""
        if not self.enabled:
            return "tv", {"_kind": "tv", "_status": None, "_why": "no FANART_API_KEY set"}
        cache_key = int(anime.get("id") or 0)
        hit = self._records.get(cache_key)
        if hit and time.time() - hit[0] < hit[2]:
            return hit[1]["_kind"], hit[1]
        kind, data, status, why, fid, how, keep = "tv", {}, None, "", None, "", RECORD_TTL
        try:
            found = await self._lookup_key(anime)
            if not found:
                why, keep = "no TheTVDB/TMDB id found for this title", 30 * 60
            else:
                kind, fid, how = found
                r = await self.http.get(f"{API}/{kind}/{fid}", params={"api_key": self.key}, timeout=15)
                status = r.status_code
                if status == 200:
                    data = r.json()
                    why = "ok"
                elif status == 404:
                    why, keep = "fanart.tv has no art for this show", 30 * 60
                elif status in (401, 403):
                    why, keep = "fanart.tv rejected the API key (check FANART_API_KEY)", 0
                    log.warning("fanart.tv rejected the API key (HTTP %s). Check FANART_API_KEY.", status)
                else:
                    why, keep = f"fanart.tv answered HTTP {status}", 0
        except Exception as e:
            why, keep = f"lookup failed: {e}", 0
            log.warning("fanart.tv lookup failed for %r: %s", anime.get("title"), e)
        counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
        log.info("fanart.tv for %r: id=%s via %s, status=%s (%s) %s", anime.get("title"), fid, how or "-", status, why,
                 counts or "")
        data = {**data, "_kind": kind, "_status": status, "_why": why, "_id": fid, "_how": how}
        if keep:
            self._records[cache_key] = (time.time(), data, keep)
            while len(self._records) > 64:
                self._records.popitem(last=False)
        return kind, data

    async def diagnose(self, anime: dict) -> list[str]:
        """Plain-language lines explaining what fanart.tv gave for this title (used by /fanart)."""
        if not self.enabled:
            return ["Key: <b>MISSING</b>. Set FANART_API_KEY (in .env or settings.py) and restart the bot."]
        self._records.pop(int(anime.get("id") or 0), None)            # always look fresh when someone is debugging
        kind, rec = await self.record(anime)
        lines = ["Key: set"]
        lines.append(f"ID used: {rec.get('_id') or 'none'}" + (f" ({kind}, from {rec['_how']})" if rec.get("_how") else ""))
        lines.append(f"fanart.tv said: HTTP {rec.get('_status') or '-'}: {rec.get('_why')}")
        if rec.get("_status") != 200:
            return lines
        kinds = MOVIE_CHARACTERS if kind == "movies" else SHOW_CHARACTERS
        chars = pick_urls(rec, kinds, prefer_lang=("", "00", "en", "ja"))
        lines.append("Character art listed: " + (", ".join(f"{k} {len(rec.get(k) or [])}" for k in kinds) or "none"))
        usable = 0
        for url in chars[:3]:
            raw = await self.fetch(url)
            if raw and prepare_character(raw):
                usable += 1
        lines.append(f"Transparent and usable (first {min(3, len(chars))} checked): {usable}")
        logos = pick_urls(rec, MOVIE_LOGOS if kind == "movies" else SHOW_LOGOS)
        lines.append("Title logos listed: " + (", ".join(f"{k} {len(rec.get(k) or [])}"
                                                         for k in (MOVIE_LOGOS if kind == 'movies' else SHOW_LOGOS)) or "none")
                     + (" (TMDB logos are tried too)" if not logos else ""))
        return lines

    async def character_urls(self, anime: dict, limit: int = 12) -> list[str]:
        kind, rec = await self.record(anime)
        kinds = MOVIE_CHARACTERS if kind == "movies" else SHOW_CHARACTERS
        return pick_urls(rec, kinds, prefer_lang=("", "00", "en", "ja"))[:limit]

    async def logo_urls(self, anime: dict) -> list[str]:
        kind, rec = await self.record(anime)
        return pick_urls(rec, MOVIE_LOGOS if kind == "movies" else SHOW_LOGOS)[:4]

    async def fetch(self, url: str) -> bytes | None:
        try:
            r = await self.http.get(url, timeout=30, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            log.warning("fanart image download failed: %s", e)
            return None
