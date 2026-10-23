"""Finding titles: AniList first, TMDB as the backup (and as an explicit choice)."""
from __future__ import annotations

import logging

from .anilist import AniListError, SearchHit, SourceError

log = logging.getLogger(__name__)


async def find_hits(app, query: str) -> tuple[list[SearchHit], str]:
    """Returns (hits, note). `note` tells people when the results come from TMDB instead of AniList.

    TMDB is used when AniList is down / erroring, and when AniList simply doesn't know the title.
    Raises SourceError only when nothing at all could be searched."""
    anilist_error: AniListError | None = None
    try:
        hits = await app.anilist.search(query)
        if hits:
            return hits, ""
    except AniListError as e:
        anilist_error = e
        log.warning("AniList search failed (%s)", e)

    if app.tmdb and app.tmdb.enabled:
        try:
            tmdb_hits = await app.tmdb.search(query)
        except SourceError as e:
            log.warning("TMDB search failed too (%s)", e)
            tmdb_hits = []
        if tmdb_hits:
            note = ("AniList isn't responding right now, so I searched TMDB instead."
                    if anilist_error else "I couldn't find that on AniList, so these come from TMDB.")
            return tmdb_hits, note
    if anilist_error:
        raise anilist_error
    return [], ""


def explain(e: Exception) -> str:
    """A message that is safe and useful to show to people."""
    if isinstance(e, AniListError) and any(w in str(e).lower() for w in ("unreachable", "isn't responding", "error 5")):
        return "AniList isn't responding right now, so I can't look that up. Please try again in a minute."
    return str(e) or "Something went wrong."
