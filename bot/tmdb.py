"""Optional TMDB lookup: finds the show/movie and returns its best landscape backdrops.

TMDB backdrops are high-definition 16:9 scenes, usually without any text on them, which is exactly the kind of
art the full-bleed designs want. Needs a free API key (TMDB_API_KEY in settings.py). If there is no key, no
confident match, or any network problem, the bot silently falls back to AniList's art.

Attribution (required by TMDB): "This product uses the TMDB API but is not endorsed or certified by TMDB."
"""
from __future__ import annotations

import asyncio
import logging
import re
from difflib import SequenceMatcher

import httpx

from .anilist import SearchHit, SourceError, readable_on, split_special, split_title, vivid
from .ids import decode_tmdb, encode_tmdb

log = logging.getLogger(__name__)
API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/"
MIN_MATCH = 0.7          # how similar the titles must be before we trust a result
MAX_BACKDROPS = 6

_SEASON_WORDS = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|i|ii|iii|iv|v|vi)"
_SEASONISH = re.compile(
    rf"\b(?:season|part|cour|series)\s*(?:\d+|{_SEASON_WORDS})\b"
    r"|\b\d+(?:st|nd|rd|th)\s+(?:season|part|cour)\b"
    r"|\b(?:final|new)\s+season\b",
    re.I,
)


class TMDBError(SourceError):
    pass


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def clean_title(title: str) -> str:
    """'Chitose Is in the Ramune Bottle 2nd Cour' -> 'Chitose Is in the Ramune Bottle'"""
    t = _SEASONISH.sub(" ", title or "")
    t = re.sub(r"\s+", " ", t).strip(" -–—:")
    t = re.sub(r"[\s:–—-]+the$", "", t, flags=re.I)       # "Attack on Titan: The Final Season" -> "...: The" -> "..."
    return t.strip(" -–—:")


def similarity(query: str, name: str) -> float:
    a, b = norm(query), norm(name)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:        # "X" vs "X: subtitle"
        ratio = max(ratio, 0.8 * min(len(a), len(b)) / max(len(a), len(b)) + 0.2)
    return ratio


def year_matches(result: dict, year: int | None) -> bool:
    ry = (result.get("first_air_date") or result.get("release_date") or "")[:4]
    return bool(year and ry.isdigit() and abs(int(ry) - year) <= 1)


def score(titles: list[str], result: dict, year: int | None) -> float:
    names = [result.get(k) for k in ("name", "original_name", "title", "original_title")]
    best = max((similarity(q, n) for q in titles for n in names if n), default=0.0)
    if year_matches(result, year):
        best += 0.06
    if 16 in (result.get("genre_ids") or []):       # TMDB genre 16 = Animation
        best += 0.06
    return best


def rank_backdrops(items: list[dict]) -> list[str]:
    """No-text images first, then the biggest, then the best rated. Skips anything under 1280px wide."""
    good = [b for b in items if b.get("file_path") and (b.get("width") or 0) >= 1280]
    good.sort(key=lambda b: (b.get("iso_639_1") is None, (b.get("width") or 0) >= 1920,
                             b.get("vote_average") or 0, b.get("width") or 0), reverse=True)
    return [b["file_path"] for b in good][:MAX_BACKDROPS]


class TMDB:
    def __init__(self, client: httpx.AsyncClient, key: str):
        self.http = client
        self.key = (key or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def image_url(self, path: str, size: str = "w1280") -> str:
        return f"{IMG}{size}{path}"

    async def _get(self, path: str, **params) -> dict:
        # a v4 "API Read Access Token" is a long JWT (sent as a Bearer header); a v3 key is 32 hex characters
        if len(self.key) > 60:
            headers, extra = {"Authorization": f"Bearer {self.key}"}, {}
        else:
            headers, extra = {}, {"api_key": self.key}
        try:
            r = await self.http.get(API + path, params={**params, **extra}, headers=headers, timeout=10)
        except httpx.HTTPError as e:
            raise TMDBError("TMDB isn't responding right now.") from e
        if r.status_code == 401:
            raise TMDBError("TMDB rejected the API key (401). Check TMDB_API_KEY in settings.py.")
        if r.status_code == 404:
            raise TMDBError("TMDB doesn't have that title.")
        if r.status_code >= 400:
            raise TMDBError(f"TMDB error {r.status_code}.")
        return r.json()

    async def find(self, meta: dict) -> tuple[str, int, dict] | None:
        english, romaji = meta.get("title_english") or "", meta.get("title_romaji") or ""
        titles: list[str] = []
        for t in (english, romaji, clean_title(english), clean_title(romaji)):
            if t and t not in titles:
                titles.append(t)
        if not titles:
            return None
        kinds = ["movie", "tv"] if meta.get("format_raw") == "MOVIE" else ["tv", "movie"]
        best: tuple[float, str, dict] | None = None
        for q in titles[:3]:
            for kind in kinds:
                data = await self._get(f"/search/{kind}", query=q, include_adult="false", language="en-US")
                for rank, r in enumerate((data.get("results") or [])[:6]):
                    sc = score(titles, r, meta.get("year"))
                    # TMDB's own search knows alternative titles (e.g. the romaji "Sousou no Frieren"). Trust its
                    # top hit when it is an animation from the same year, even if the names differ.
                    if rank == 0 and 16 in (r.get("genre_ids") or []) and year_matches(r, meta.get("year")):
                        sc = max(sc, MIN_MATCH + 0.02)
                    if best is None or sc > best[0]:
                        best = (sc, kind, r)
            if best and best[0] >= 0.95:
                break
        if not best or best[0] < MIN_MATCH:
            return None
        return best[1], best[2]["id"], best[2]

    async def backdrops(self, meta: dict) -> list[str]:
        """Ranked file paths of landscape backdrops for this anime ([] when nothing trustworthy is found)."""
        if meta.get("tmdb_ref"):                      # the title itself came from TMDB: no searching needed
            kind, tid = meta["tmdb_ref"]
            result = {}
        else:
            found = await self.find(meta)
            if not found:
                return []
            kind, tid, result = found
        data = await self._get(f"/{kind}/{tid}/images", include_image_language="en,ja,null")
        paths = rank_backdrops(data.get("backdrops") or [])
        if not paths and result.get("backdrop_path"):
            paths = [result["backdrop_path"]]
        return paths

    # ------------------------------------------------------------------ TMDB as a source of titles
    async def search(self, query: str) -> list[SearchHit]:
        """Search TV and movies. Animation is ranked first (this is an anime bot), then by name similarity."""
        tv, movie = await asyncio.gather(
            *(self._get(f"/search/{k}", query=query, include_adult="false", language="en-US") for k in ("tv", "movie")),
            return_exceptions=True)
        if isinstance(tv, Exception) and isinstance(movie, Exception):
            raise tv
        scored = []
        for kind, data in (("tv", tv), ("movie", movie)):
            if isinstance(data, Exception):
                continue
            for r in (data.get("results") or [])[:8]:
                if not (r.get("poster_path") or r.get("backdrop_path")):
                    continue                              # nothing to build a poster from
                name = r.get("name") or r.get("title") or ""
                sim = max(similarity(query, name), similarity(query, r.get("original_name") or r.get("original_title") or ""))
                animation = 16 in (r.get("genre_ids") or [])
                scored.append((sim + (0.25 if animation else 0) + min(r.get("popularity") or 0, 100) / 1000, kind, r, name))
        scored.sort(key=lambda x: x[0], reverse=True)
        hits, seen = [], set()
        for _, kind, r, name in scored:
            mid = encode_tmdb(kind, r["id"])
            if mid in seen:
                continue
            seen.add(mid)
            date = (r.get("first_air_date") or r.get("release_date") or "")[:4]
            hits.append(SearchHit(mid, name or "Untitled", int(date) if date.isdigit() else None,
                                  "TV" if kind == "tv" else "Movie", source="tmdb", extra="TV" if kind == "tv" else "Movie"))
        return hits[:5]

    async def media(self, media_id: int) -> dict:
        """Everything the templates need for one TMDB title, in the same shape AniList titles have."""
        ref = decode_tmdb(media_id)
        if not ref:
            raise TMDBError("That isn't a TMDB title.")
        kind, tid = ref
        d = await self._get(f"/{kind}/{tid}", language="en-US", append_to_response="credits")
        is_tv = kind == "tv"
        title = (d.get("name") if is_tv else d.get("title")) or "Untitled"
        original = (d.get("original_name") if is_tv else d.get("original_title")) or ""
        date = (d.get("first_air_date") if is_tv else d.get("release_date")) or ""
        year = int(date[:4]) if date[:4].isdigit() else None
        genres = [g["name"] for g in (d.get("genres") or []) if g.get("name")]
        vote = float(d.get("vote_average") or 0)
        company = next(iter(d.get("production_companies") or []), None) or next(iter(d.get("networks") or []), None) or {}
        episodes = d.get("number_of_episodes") if is_tv else None
        runtime = d.get("runtime") if not is_tv else next(iter(d.get("episode_run_time") or []), None)
        status = {"Returning Series": "Releasing", "Ended": "Finished", "Canceled": "Cancelled"}.get(d.get("status") or "", d.get("status") or "")
        poster, backdrop = d.get("poster_path"), d.get("backdrop_path")
        cast = []
        for c in ((d.get("credits") or {}).get("cast") or [])[:3]:
            if c.get("name"):
                cast.append({"name": c.get("character") or c["name"], "image_url": self.image_url(c["profile_path"], "w185") if c.get("profile_path") else None,
                             "role": "MAIN", "va_name": c["name"], "va_image_url": None})
        title_a, title_b = split_title(title)
        title_big, title_small = split_special(title)
        return {
            "id": media_id, "url": f"https://www.themoviedb.org/{kind}/{tid}", "source": "tmdb", "tmdb_ref": (kind, tid),
            "title": title, "title_native": original if original and original != title else None,
            "title_english": title, "title_romaji": original, "format_raw": "TV" if is_tv else "MOVIE",
            "title_a": title_a, "title_b": title_b, "title_big": title_big, "title_small": title_small,
            "description": (d.get("overview") or "").strip() or "No synopsis available.",
            "format": "TV" if is_tv else "Movie", "status": status, "season": "", "year": year,
            "episodes": episodes, "duration": runtime,
            "season_line": str(year) if year else ("TV" if is_tv else "Movie"),
            "episodes_label": (f"{episodes} episodes" if episodes else "") if is_tv else (f"{runtime} min" if runtime else ""),
            "score10": round(vote, 1) if vote else None, "stars5": round(vote / 2, 2), "star_pct": round(vote * 10, 1),
            "genres": genres[:3], "genres4": genres[:4], "studio": company.get("name"),
            "accent": "#7c5cff", "accent_fg": "#fff", "accent_vivid": vivid("#7c5cff"), "accent_vivid_fg": "#fff",
            "needs_accent": True,                          # AnimeCache fills these in from the poster once it is downloaded
            "banner_url": self.image_url(backdrop, "w1280") if backdrop else None,
            "cover_url": self.image_url(poster or backdrop, "w780") if (poster or backdrop) else None,
            "thumb_urls": [], "characters": cast,
        }
