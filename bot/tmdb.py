"""Optional TMDB lookup: finds the show/movie and returns its best landscape backdrops.

TMDB backdrops are high-definition 16:9 scenes, usually without any text on them, which is exactly the kind of
art the full-bleed designs want. Needs a free API key (TMDB_API_KEY in settings.py). If there is no key, no
confident match, or any network problem, the bot silently falls back to AniList's art.

Attribution (required by TMDB): "This product uses the TMDB API but is not endorsed or certified by TMDB."
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

import httpx

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


class TMDBError(Exception):
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
        r = await self.http.get(API + path, params={**params, **extra}, headers=headers, timeout=10)
        if r.status_code == 401:
            raise TMDBError("TMDB rejected the API key (401). Check TMDB_API_KEY in settings.py.")
        r.raise_for_status()
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
        found = await self.find(meta)
        if not found:
            return []
        kind, tid, result = found
        data = await self._get(f"/{kind}/{tid}/images", include_image_language="en,ja,null")
        paths = rank_backdrops(data.get("backdrops") or [])
        if not paths and result.get("backdrop_path"):
            paths = [result["backdrop_path"]]
        return paths
