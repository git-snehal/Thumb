"""Ids for titles that don't come from AniList.

AniList ids are positive integers. A TMDB title is stored as a NEGATIVE integer, so the two can never be confused
(TMDB ids overlap AniList ids numerically) and every place that already carries a media id (button data, saved
settings, caches, file names) keeps working unchanged.
"""
from __future__ import annotations


def encode_tmdb(kind: str, tmdb_id: int) -> int:
    """('tv', 1399) -> -2798 ; ('movie', 603) -> -1207"""
    return -(int(tmdb_id) * 2 + (1 if kind == "movie" else 0))


def decode_tmdb(media_id: int) -> tuple[str, int] | None:
    """The inverse of encode_tmdb, or None for an ordinary (AniList) id."""
    if media_id >= 0:
        return None
    k = -media_id
    return ("movie" if k % 2 else "tv"), k // 2


def is_tmdb(media_id: int) -> bool:
    return media_id < 0
