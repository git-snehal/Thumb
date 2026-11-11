"""Extra poster art from sources that need no API key: Jikan (MyAnimeList) and Kitsu.

Both give PORTRAIT pictures, so the bot marks them as such and never treats them as wide backdrops.
Every function returns [] on any problem: these are a bonus on top of AniList and TMDB.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

JIKAN = "https://api.jikan.moe/v4"
KITSU = "https://kitsu.io/api/edge"
MAX_EXTRA = 8


def jikan_urls(payload: dict) -> list[str]:
    """Large image urls from a Jikan /anime/{id}/pictures response."""
    out: list[str] = []
    for item in payload.get("data") or []:
        jpg = item.get("jpg") or {}
        url = jpg.get("large_image_url") or jpg.get("image_url")
        if url and url not in out:
            out.append(url)
    return out


def kitsu_urls(payload: dict) -> list[str]:
    """Poster urls from a Kitsu /mappings?include=item response."""
    out: list[str] = []
    for inc in payload.get("included") or []:
        poster = ((inc.get("attributes") or {}).get("posterImage")) or {}
        url = poster.get("original") or poster.get("large")
        if url and url not in out:
            out.append(url)
    return out


async def jikan(http: httpx.AsyncClient, mal_id: int | None) -> list[str]:
    if not mal_id:
        return []
    try:
        r = await http.get(f"{JIKAN}/anime/{int(mal_id)}/pictures", timeout=10)
        if r.status_code != 200:
            return []
        return jikan_urls(r.json())
    except (httpx.HTTPError, ValueError) as e:
        log.info("Jikan pictures unavailable: %s", e)
        return []


async def kitsu(http: httpx.AsyncClient, anilist_id: int | None) -> list[str]:
    if not anilist_id or anilist_id < 0:
        return []
    try:
        r = await http.get(f"{KITSU}/mappings", timeout=10, headers={"Accept": "application/vnd.api+json"},
                           params={"filter[externalSite]": "anilist/anime", "filter[externalId]": int(anilist_id),
                                   "include": "item"})
        if r.status_code != 200:
            return []
        return kitsu_urls(r.json())
    except (httpx.HTTPError, ValueError) as e:
        log.info("Kitsu poster unavailable: %s", e)
        return []


async def extra_posters(http: httpx.AsyncClient, anime: dict) -> list[str]:
    """Jikan + Kitsu pictures for an AniList title (TMDB-only titles have no MAL/AniList id, so none)."""
    import asyncio

    if anime.get("source") == "tmdb":
        return []
    found = await asyncio.gather(jikan(http, anime.get("mal_id")), kitsu(http, anime.get("id")))
    out: list[str] = []
    for urls in found:
        for u in urls:
            if u not in out:
                out.append(u)
    return out[:MAX_EXTRA]


def source_name(url: str) -> str:
    if "myanimelist" in url:
        return "MyAnimeList"
    if "kitsu" in url:
        return "Kitsu"
    return "TMDB"
