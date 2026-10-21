"""Check TMDB for a title: which show it matches and how many HD backdrops it has.

    python -m scripts.tmdb_check "The Eminence in Shadow" --key YOUR_TMDB_KEY
    python -m scripts.tmdb_check --id 130298 --key YOUR_TMDB_KEY        # by AniList id (uses its real titles)

Run this once with your key. If it says "no confident match" for a title, the bot will simply use AniList art for it.
"""
from __future__ import annotations

import argparse
import asyncio

import httpx

from bot import config
from bot.anilist import AniList
from bot.tmdb import TMDB, TMDBError


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("title", nargs="?", default="")
    ap.add_argument("--id", type=int, help="AniList id")
    ap.add_argument("--key", default=config._get("TMDB_API_KEY"), help="TMDB API key (default: settings.py)")
    args = ap.parse_args()
    if not args.key:
        ap.error("no TMDB key: pass --key or fill TMDB_API_KEY in settings.py")
    if not (args.title or args.id):
        ap.error("give a title or --id")

    async with httpx.AsyncClient(headers={"User-Agent": "anime-thumb-bot-check"}) as http:
        meta = {"title_english": args.title, "title_romaji": "", "format_raw": "TV", "year": None}
        if args.id:
            meta = await AniList(http).media(args.id)
            print(f"AniList: {meta['title']} ({meta.get('year')}, {meta.get('format_raw')})")
        tmdb = TMDB(http, args.key)
        try:
            found = await tmdb.find(meta)
            if not found:
                print("TMDB: no confident match (the bot would use AniList art for this title)")
                return
            kind, tid, res = found
            print(f"TMDB match: {res.get('name') or res.get('title')} [{kind} {tid}] "
                  f"{(res.get('first_air_date') or res.get('release_date') or '')[:4]}")
            paths = await tmdb.backdrops(meta)
            print(f"{len(paths)} usable backdrop(s) (>= 1280px wide), best first:")
            for p in paths:
                print("  ", tmdb.image_url(p))
        except TMDBError as e:
            print("TMDB error:", e)
        except httpx.HTTPError as e:
            print("Network error talking to TMDB:", e)


if __name__ == "__main__":
    asyncio.run(main())
