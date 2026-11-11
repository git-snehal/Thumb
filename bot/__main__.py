from __future__ import annotations

import asyncio
import logging
import signal
import time
from pathlib import Path

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.types import BotCommand

from . import VERSION, config, cutout, icons, instance, texts
from .anilist import AniList
from .app import App
from .assets import AnimeCache
from .customize import router as customize_router
from .fanart import Fanart
from .guard import AllowListMiddleware, RateLimiter
from .handlers import router as anime_router
from .registry import load_templates
from .render import Renderer
from .start import router as start_router
from .store import Store
from .tmdb import TMDB


def setup_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "asyncio"):          # one INFO line per HTTP request is just noise
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def heartbeat(path: Path) -> None:
    """Touch a file every 30s. The Docker HEALTHCHECK (deploy/healthcheck.py) fails if it goes stale,
    which means the event loop is stuck and the container should be restarted."""
    while True:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(time.time()))
        except OSError:
            pass
        await asyncio.sleep(30)


async def main() -> None:
    cfg = config.load()
    setup_logging(cfg.log_level)
    if cfg.kill_old:
        stopped = instance.stop_stale_instances()
        logging.info("Stopped leftover bot process(es): %s", stopped or "none found")
    icons.configure(cfg.icons)
    texts.FANCY = cfg.fancy_text

    http = httpx.AsyncClient(headers={"User-Agent": f"anime-thumb-bot/{VERSION}"})
    anilist = AniList(http)
    renderer = Renderer(cfg.templates_dir, cfg.assets_dir, cfg.render_concurrency)
    tmdb = TMDB(http, cfg.tmdb_key)
    texts.TMDB_ON = tmdb.enabled
    fanart = Fanart(http, cfg.fanart_key, tmdb, cfg.data_dir)
    texts.FANART_ON = fanart.enabled
    cache = AnimeCache(anilist, http, cfg.cache_ttl, tmdb=tmdb, fanart=fanart, extra_art=cfg.extra_art,
                       upscale=cfg.upscale_art, title_logos=cfg.title_logos)
    app = App(cfg, anilist, cache, renderer,
              load_templates(cfg.overrides_file), Store(cfg.db_path, cfg.logos_dir),
              RateLimiter(cfg.rate_limit, exempt=cfg.admin_ids))

    bot = Bot(cfg.bot_token, default=DefaultBotProperties(link_preview_is_disabled=True))
    dp = Dispatcher()
    guard = AllowListMiddleware(cfg.allowed_users, cfg.admin_ids)         # does nothing unless ALLOWED_USER_IDS is set
    dp.message.outer_middleware(guard)
    dp.callback_query.outer_middleware(guard)
    # order matters: input-waiting handlers first, the catch-all emoji helper last
    dp.include_routers(customize_router, anime_router, start_router)
    dp["app"] = app

    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError:
        logging.error("Telegram rejected BOT_TOKEN. Check it with @BotFather (/mybots -> API Token).")
        await http.aclose()
        raise SystemExit(1)
    except Exception as e:      # network hiccup at boot: keep going, polling retries by itself
        me = None
        logging.warning("Couldn't reach Telegram yet (%s). Will keep retrying.", e)
    logging.info("Anime Thumb Bot v%s as @%s | TMDB art: %s | fanart.tv: %s | AI cutout: %s | allow-list: %s | rate limit: %s/min | data: %s",
                 VERSION, me.username if me else "?", "on" if tmdb.enabled else "off", "on" if fanart.enabled else "off",
                 "on" if cfg.auto_cutout else "off",
                 f"{len(cfg.allowed_users)} users" if cfg.allowed_users else "open", cfg.rate_limit or "unlimited", cfg.data_dir)

    commands = ([
        BotCommand(command="start", description="Start the bot"),
        BotCommand(command="poster", description="Make a thumbnail: /poster <name>"),
        BotCommand(command="settings", description="Brand text, logo, position and font"),
        BotCommand(command="help", description="Guide and command list"),
        BotCommand(command="version", description="Which version of the bot is running"),
        BotCommand(command="emojiid", description="Get animated emoji IDs"),
        BotCommand(command="cancel", description="Cancel a pending upload"),
    ])
    try:
        await bot.set_my_commands(commands)
    except Exception as e:       # not worth crashing for: the menu is only cosmetic, and polling retries by itself
        logging.warning("Couldn't register the command menu yet (%s).", e)
    if cfg.auto_cutout:   # load (and on first run, download) the background-removal model without blocking startup
        asyncio.create_task(asyncio.to_thread(cutout.warm_up))
    beat = asyncio.create_task(heartbeat(cfg.heartbeat_file))
    stop = asyncio.Event()

    async def stop_polling_quietly() -> None:
        try:
            await dp.stop_polling()
        except RuntimeError:                         # not polling right now (e.g. waiting to retry): nothing to stop
            pass

    pending: set[asyncio.Task] = set()

    def request_stop() -> None:                      # SIGTERM (docker stop / systemd) and SIGINT (Ctrl+C)
        stop.set()
        task = asyncio.get_running_loop().create_task(stop_polling_quietly())
        pending.add(task)
        task.add_done_callback(pending.discard)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, request_stop)
        except (NotImplementedError, RuntimeError):  # e.g. Windows: Ctrl+C still works through asyncio.run
            pass

    logging.info("Bot is up. Stop it with Ctrl+C / SIGTERM.")
    try:
        delay = 5
        while not stop.is_set():
            try:
                # aiogram talks to Telegram before it starts polling, so a server that boots before its network is
                # ready would otherwise exit. Keep retrying (5s, 10s ... 60s) instead of crash-looping.
                await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), handle_signals=False)
                break
            except TelegramUnauthorizedError:
                logging.error("Telegram rejected BOT_TOKEN. Check it with @BotFather (/mybots -> API Token).")
                raise SystemExit(1)
            except Exception as e:
                logging.warning("Telegram unreachable (%s). Retrying in %ss.", str(e)[:120], delay)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, 60)
    finally:
        beat.cancel()
        await renderer.close()
        await http.aclose()
        await bot.session.close()
        logging.info("Shut down cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
