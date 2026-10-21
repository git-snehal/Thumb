"""/start (animated), /help, and the Premium-emoji ID helper."""
from __future__ import annotations

import asyncio
import os
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from . import VERSION, icons
from .app import App, guard_icons
from .keyboards import btn, start_kb
from .texts import esc, help_text, start_frames, start_text

router = Router()
STARTED = time.strftime("%Y-%m-%d %H:%M:%S")


def _back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[btn("Back", "home", "back", "↩️")]])


@router.message(CommandStart())
async def start(message: Message) -> None:
    frames = start_frames()
    sent = await message.answer(frames[0], parse_mode="HTML")
    for frame in frames[1:]:
        await asyncio.sleep(0.6)
        try:
            await sent.edit_text(frame, parse_mode="HTML")
        except TelegramBadRequest:
            pass
    await asyncio.sleep(0.6)
    name = message.from_user.first_name or "there"
    uid = message.from_user.id
    await guard_icons(lambda: sent.edit_text(start_text(name), parse_mode="HTML", reply_markup=start_kb(uid)))


@router.callback_query(F.data == "home")
async def home(call: CallbackQuery) -> None:
    await call.answer()
    uid, name = call.from_user.id, call.from_user.first_name or "there"
    await guard_icons(lambda: call.message.edit_text(start_text(name), parse_mode="HTML", reply_markup=start_kb(uid)))


@router.callback_query(F.data == "help")
async def help_cb(call: CallbackQuery) -> None:
    await call.answer()
    await guard_icons(lambda: call.message.edit_text(help_text(), parse_mode="HTML", reply_markup=_back_kb()))


@router.callback_query(F.data == "go")
async def go(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.answer("Send <code>/poster Solo Leveling</code> (any title) and I'll build it. 🎬", parse_mode="HTML")


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(help_text(), parse_mode="HTML")


@router.message(Command("emojiid"))
async def emojiid_cmd(message: Message) -> None:
    status = "on" if icons.any_configured() else "not set up yet"
    await message.answer(
        "<b>Animated button icons</b> (status: " + status + ")\n\n"
        "1. Send me a message containing one or more <b>Premium animated emoji</b>.\n"
        "2. I'll reply with each emoji's ID.\n"
        "3. Paste the IDs into the <code>ICONS</code> section of <code>settings.py</code> and restart the bot.\n\n"
        "<i>Telegram only accepts these icons if the account that owns this bot has Telegram Premium.</i>",
        parse_mode="HTML")


def _custom_emoji_ids(m: Message) -> list[str]:
    ents = (m.entities or []) + (m.caption_entities or [])
    return [e.custom_emoji_id for e in ents if e.type == "custom_emoji" and e.custom_emoji_id]


@router.message(lambda m: bool(_custom_emoji_ids(m)))
async def emoji_ids(message: Message) -> None:
    ids = _custom_emoji_ids(message)
    lines = "\n".join(f"{i}. <code>{esc(x)}</code>" for i, x in enumerate(ids, 1))
    await message.answer(
        f"<b>Found {len(ids)} custom emoji:</b>\n{lines}\n\n"
        "Paste an ID between the quotes of a slot in <code>ICONS</code> inside <code>settings.py</code>, "
        "e.g. <code>\"template\": \"" + esc(ids[0]) + "\"</code>",
        parse_mode="HTML")


@router.message(Command("version"))
async def version_cmd(message: Message, app: App) -> None:
    """If two copies of the bot ever run at once, this shows which one answered. Also reports what's switched on."""
    assets = app.renderer.special_assets
    have = " ".join(f"{k} {'✓' if v else '✗'}" for k, v in assets.items())
    await message.answer(
        f"<b>Anime Thumb Bot</b> v{VERSION}\nrunning since {STARTED}\nprocess {os.getpid()}\n\n"
        f"special defaults: {'on' if app.cfg.special_defaults else 'off'} ({have})\n"
        f"TMDB art: {'on' if app.cache.tmdb and app.cache.tmdb.enabled else 'off (no key)'}\n"
        f"AI cutout: {'on' if app.cfg.auto_cutout else 'off'}\n"
        f"rate limit: {app.cfg.rate_limit or 'off'}/min · allow-list: "
        f"{str(len(app.cfg.allowed_users)) + ' users' if app.cfg.allowed_users else 'open'}", parse_mode="HTML")
