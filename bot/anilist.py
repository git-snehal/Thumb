"""AniList GraphQL client: search + full metadata, normalised for the templates."""
from __future__ import annotations

import asyncio
import html
import re
import time
from dataclasses import dataclass

import httpx

from .ids import encode_tmdb

URL = "https://graphql.anilist.co"

SEARCH_Q = """
query ($q: String) {
  Page(perPage: 5) {
    media(search: $q, type: ANIME, sort: SEARCH_MATCH) {
      id
      title { romaji english native }
      seasonYear
      format
    }
  }
}"""

MEDIA_Q = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    idMal
    siteUrl
    title { romaji english native }
    description(asHtml: false)
    format
    status
    season
    seasonYear
    episodes
    duration
    averageScore
    genres
    bannerImage
    coverImage { extraLarge large color }
    studios(isMain: true) { nodes { name } }
    characters(sort: [ROLE, FAVOURITES_DESC], perPage: 3) {
      edges {
        role
        node { name { full } image { large } }
        voiceActors(language: JAPANESE, sort: RELEVANCE) { name { full } image { large } }
      }
    }
    streamingEpisodes { title thumbnail }
  }
}"""


class SourceError(Exception):
    """A title source (AniList or TMDB) couldn't answer. The message is safe to show to people."""


class AniListError(SourceError):
    pass


@dataclass
class SearchHit:
    id: int
    title: str
    year: int | None
    format: str | None
    source: str = "anilist"          # "anilist" or "tmdb"
    extra: str = ""                  # e.g. "TV" / "Movie" for TMDB results

    @property
    def label(self) -> str:
        bits = [self.title]
        if self.year:
            bits.append(f"({self.year})")
        text = " ".join(bits)
        if self.extra:
            text = f"{text[:48]} · {self.extra}"
        return text[:60]


def _title(t: dict) -> str:
    return t.get("english") or t.get("romaji") or t.get("native") or "Unknown"


_TAG = re.compile(r"<[^>]+>")
_SOURCE = re.compile(r"\(\s*Source:[^)]*\)|\[\s*Written by[^\]]*\]", re.I)


def clean_description(raw: str | None) -> str:
    if not raw:
        return "No synopsis available."
    text = re.sub(r"<br\s*/?>", " ", raw, flags=re.I)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = _SOURCE.sub("", text)
    return re.sub(r"\s+", " ", text).strip() or "No synopsis available."


def split_title(title: str) -> tuple[str, str]:
    """Split a title into two lines of similar length (for two-tone headings)."""
    words = title.split()
    if len(words) < 2:
        return title, ""
    best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    return " ".join(words[:best]), " ".join(words[best:])


def split_special(title: str) -> tuple[str, str]:
    """(big, small) for the vertical title: the last word is big, the rest sits beside it, small."""
    words = title.split()
    if len(words) < 2:
        return title, ""
    return words[-1], " ".join(words[:-1])


def readable_on(hex_color: str) -> str:
    """Black or white, whichever reads better on top of hex_color."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return "#fff"
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return "#111" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#fff"


def vivid(hex_color: str) -> str:
    """A punchier version of the cover colour for buttons and highlights."""
    import colorsys
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return "#ff4d6d"
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < 0.12:                                  # grey/white cover colour: no hue to keep
        return "#ff4d6d"
    r, g, b = colorsys.hsv_to_rgb(hue, max(s, 0.62), max(v, 0.9))
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def parse_query(text: str) -> tuple[str, int | str]:
    """("id", n) for AniList links / `id:123`, for TMDB links / `tmdb:tv/1399` (n is a negative TMDB id),
    otherwise ("search", text)."""
    text = text.strip()
    m = re.search(r"themoviedb\.org/(tv|movie)/(\d+)", text) or re.fullmatch(r"tmdb:\s*(tv|movie)\s*/\s*(\d+)", text, re.I)
    if m:
        return "id", encode_tmdb(m.group(1).lower(), int(m.group(2)))
    m = re.search(r"anilist\.co/anime/(\d+)", text)
    if m:
        return "id", int(m.group(1))
    m = re.fullmatch(r"id:\s*(\d+)", text, re.I)
    if m:
        return "id", int(m.group(1))
    return "search", text


class AniList:
    DOWN_FOR = 45          # seconds to skip AniList after it failed, so people aren't kept waiting on every request

    def __init__(self, client: httpx.AsyncClient):
        self.http = client
        self._down_until = 0.0

    @property
    def is_down(self) -> bool:
        return time.monotonic() < self._down_until

    def _trip(self) -> None:
        self._down_until = time.monotonic() + self.DOWN_FOR

    async def _gql(self, query: str, variables: dict, timeout: float = 20, attempts: int = 3) -> dict:
        if self.is_down:
            raise AniListError("AniList isn't responding right now.")
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                r = await self.http.post(URL, json={"query": query, "variables": variables}, timeout=timeout)
            except httpx.HTTPError as e:
                if last:
                    self._trip()
                    raise AniListError(f"AniList unreachable: {e}") from e
                await asyncio.sleep(1 + attempt)
                continue
            if r.status_code == 429:
                await asyncio.sleep(min(int(r.headers.get("Retry-After", "5")), 30))
                continue
            if r.status_code == 404:
                raise AniListError("Anime not found.")
            if r.status_code >= 500:                       # AniList itself is having trouble: retry, then give up fast
                if last:
                    self._trip()
                    raise AniListError(f"AniList error {r.status_code}")
                await asyncio.sleep(1 + attempt)
                continue
            if r.status_code >= 400:
                raise AniListError(f"AniList error {r.status_code}")
            self._down_until = 0.0
            return r.json()["data"]
        self._trip()
        raise AniListError("AniList is rate-limiting us, try again shortly.")

    async def search(self, query: str) -> list[SearchHit]:
        data = await self._gql(SEARCH_Q, {"q": query}, timeout=7, attempts=2)   # fail fast so the TMDB fallback starts soon
        return [
            SearchHit(m["id"], _title(m["title"]), m.get("seasonYear"), m.get("format"))
            for m in data["Page"]["media"]
        ]

    async def media(self, media_id: int) -> dict:
        """Fetch one anime and normalise it into a flat dict the templates use."""
        m = (await self._gql(MEDIA_Q, {"id": media_id}))["Media"]
        score = m.get("averageScore")
        studios = [s["name"] for s in (m.get("studios") or {}).get("nodes", [])]
        chars = []
        for e in (m.get("characters") or {}).get("edges", []):
            va = (e.get("voiceActors") or [None])[0]
            chars.append(
                {
                    "name": e["node"]["name"]["full"],
                    "image_url": (e["node"].get("image") or {}).get("large"),
                    "role": e.get("role"),
                    "va_name": va["name"]["full"] if va else None,
                    "va_image_url": (va.get("image") or {}).get("large") if va else None,
                }
            )
        thumbs = [
            s["thumbnail"] for s in (m.get("streamingEpisodes") or []) if s.get("thumbnail")
        ][:3]
        cover = m.get("coverImage") or {}
        accent = cover.get("color") or "#7c5cff"
        fmt = (m.get("format") or "").replace("_", " ")
        season_word = (m.get("season") or "").title()
        season_line = f"{season_word} {m['seasonYear']}".strip() if m.get("seasonYear") else ("TV" if fmt == "TV" else fmt.title())
        episodes_label = f"{m['episodes']} episodes" if m.get("episodes") else ""
        title = _title(m["title"])
        title_a, title_b = split_title(title)
        title_big, title_small = split_special(title)
        return {
            "id": m["id"],
            "mal_id": m.get("idMal"),
            "season_line": season_line,
            "episodes_label": episodes_label,
            "title_english": m["title"].get("english"),
            "title_romaji": m["title"].get("romaji"),
            "format_raw": m.get("format") or "",
            "title_big": title_big,
            "title_small": title_small,
            "title_a": title_a,
            "title_b": title_b,
            "url": m.get("siteUrl"),
            "title": title,
            "title_native": m["title"].get("native"),
            "description": clean_description(m.get("description")),
            "format": "TV" if fmt == "TV" else fmt.title(),
            "status": (m.get("status") or "").replace("_", " ").title(),
            "season": (m.get("season") or "").title(),
            "year": m.get("seasonYear"),
            "episodes": m.get("episodes"),
            "duration": m.get("duration"),
            "score10": round(score / 10, 1) if score else None,
            "stars5": round(score / 20, 2) if score else 0,
            "star_pct": round((score or 0), 1),  # 0-100 maps straight to the star fill %
            "genres": (m.get("genres") or [])[:3],
            "genres4": (m.get("genres") or [])[:4],
            "studio": studios[0] if studios else None,
            "accent": accent,
            "accent_fg": readable_on(accent),
            "accent_vivid": vivid(accent),
            "accent_vivid_fg": readable_on(vivid(accent)),
            "banner_url": m.get("bannerImage"),
            "cover_url": cover.get("extraLarge") or cover.get("large"),
            "thumb_urls": thumbs,
            "characters": chars,
        }
