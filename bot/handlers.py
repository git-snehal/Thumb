"""Anime lookup + banner message flow."""
from __future__ import annotations

import logging
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaPhoto, Message

from .anilist import SourceError, parse_query
from .app import BUSY, App, NeedCharacter, RateLimited, guard_icons
from .customize import ask_character
from .search import explain, find_hits
from .keyboards import caption, current_key, grid_caption, grid_kb, picker_kb, template_kb

log = logging.getLogger(__name__)
router = Router()

_COOLDOWN: dict[int, float] = {}   # user id -> last /poster time
_LAST_QUERY: dict[int, str] = {}   # user id -> their last search text (for the 'Search TMDB' button)


async def send_banner(message: Message, app: App, uid: int, media_id: int) -> None:
    status = await message.answer("⏳ Building your thumbnail…")
    spec = app.templates[0]
    try:
        anime, img = await app.render(media_id, spec, uid)
    except RateLimited as e:
        await status.edit_text(f"⏳ Slow down a little: try again in {e.retry_after:.0f}s.")
        return
    except SourceError as e:
        await status.edit_text(f"❌ {explain(e)}")
        return
    except Exception:
        log.exception("render failed")
        await status.edit_text("❌ Couldn't build that one. Try again in a moment.")
        return
    await guard_icons(lambda: message.answer_photo(
        BufferedInputFile(img, "poster.jpg"),
        caption=caption(anime["title"], spec.key),
        parse_mode="HTML",
        reply_markup=template_kb(uid, media_id, app.templates, spec.key),
    ))
    await status.delete()


@router.message(Command("poster"))
async def poster_cmd(message: Message, command: CommandObject, app: App) -> None:
    query = (command.args or "").strip()
    if not query and message.reply_to_message:
        query = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()
    if not query:
        await message.answer("Usage: <code>/poster Solo Leveling</code>", parse_mode="HTML")
        return

    uid = message.from_user.id
    if time.time() - _COOLDOWN.get(uid, 0) < 3:
        return
    _COOLDOWN[uid] = time.time()

    kind, value = parse_query(query)
    if kind == "id":
        await send_banner(message, app, uid, int(value))
        return

    try:
        hits, note = await find_hits(app, str(value))
    except SourceError as e:
        await message.answer(f"❌ {explain(e)}")
        return
    if not hits:
        await message.answer("😕 No anime found for that. Try the English or romaji title."
                             + (" I looked on TMDB too." if app.tmdb and app.tmdb.enabled else ""))
        return
    _LAST_QUERY[uid] = str(value)
    if len(_LAST_QUERY) > 500:                       # keep this small
        _LAST_QUERY.pop(next(iter(_LAST_QUERY)))
    exact = hits[0].title.lower() == str(value).lower()
    if len(hits) == 1 or exact:
        if note:
            await message.answer(f"ℹ️ {note}")
        await send_banner(message, app, uid, hits[0].id)
    else:
        offer = hits[0].source == "anilist" and bool(app.tmdb and app.tmdb.enabled)
        await message.answer(f"{note + chr(10) if note else ''}Which one did you mean?",
                             reply_markup=picker_kb(uid, hits, offer_tmdb=offer))


@router.callback_query(F.data.startswith("tq:"))
async def search_tmdb(call: CallbackQuery, app: App) -> None:
    """'Not here? Search TMDB': run the same search on TMDB and replace the list."""
    uid = int(call.data.split(":")[1])
    if call.from_user.id != uid:
        await call.answer("This menu belongs to someone else.", show_alert=True)
        return
    query = _LAST_QUERY.get(uid)
    if not query or not (app.tmdb and app.tmdb.enabled):
        await call.answer("Send /poster and the name again.", show_alert=True)
        return
    await call.answer("Searching TMDB…")
    try:
        hits = await app.tmdb.search(query)
    except SourceError as e:
        await call.message.answer(f"❌ {explain(e)}")
        return
    if not hits:
        await call.message.answer("😕 TMDB doesn't have that either.")
        return
    await call.message.edit_text("From TMDB. Which one did you mean?", reply_markup=picker_kb(uid, hits))


@router.callback_query(F.data.startswith("p:"))
async def pick(call: CallbackQuery, app: App) -> None:
    _, uid, mid = call.data.split(":")
    if call.from_user.id != int(uid):
        await call.answer("This menu belongs to someone else.", show_alert=True)
        return
    await call.answer()
    await send_banner(call.message, app, int(uid), int(mid))
    try:
        await call.message.delete()
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("t:"))
async def switch(call: CallbackQuery, app: App, state: FSMContext) -> None:
    _, uid, mid, key = call.data.split(":")
    if call.from_user.id != int(uid):
        await call.answer("Only the person who made this can change it.", show_alert=True)
        return
    spec = app.spec(key)
    if spec is None:
        await call.answer("That template isn't available any more.", show_alert=True)
        return
    if spec.special and not await app.store.get_character(int(uid), int(mid)):
        await call.answer()
        await ask_character(call.message, state, int(uid), int(mid), key)   # first time: ask for the character
        return
    ref = (call.message.chat.id, call.message.message_id)
    if ref in BUSY:
        await call.answer("Still rendering, one moment…")
        return
    current = current_key(call.message)
    if current == key:
        await call.answer("Already using this one.")
        return

    BUSY.add(ref)
    await call.answer(f"Rendering {spec.label}…")
    try:
        anime, img = await app.render(int(mid), spec, int(uid))
        await guard_icons(lambda: call.message.edit_media(
            InputMediaPhoto(media=BufferedInputFile(img, "poster.jpg"), caption=caption(anime["title"], key), parse_mode="HTML"),
            reply_markup=template_kb(int(uid), int(mid), app.templates, key),
        ))
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            log.exception("edit failed")
    except RateLimited as e:
        await call.message.answer(f"⏳ Slow down a little: try again in {e.retry_after:.0f}s.")
    except Exception:
        log.exception("render failed")
        await call.message.answer("❌ Couldn't render that template. Try again.")
    finally:
        BUSY.discard(ref)


async def _send_file(call: CallbackQuery, app: App, hd: bool) -> None:
    _, uid, mid, key = call.data.split(":")
    if call.from_user.id != int(uid):
        await call.answer("Only the person who made this can download it.", show_alert=True)
        return
    spec = app.spec(key)
    if spec is None:
        await call.answer("Template unavailable.", show_alert=True)
        return
    await call.answer("Preparing the 2x HD file (a few seconds)…" if hd else "Preparing the full-quality file…")
    try:
        anime, png = await app.render(int(mid), spec, int(uid), fmt="png", hd=hd, cost=2 if hd else 1)
    except RateLimited as e:
        await call.message.answer(f"⏳ Slow down a little: try again in {e.retry_after:.0f}s.")
        return
    except Exception:
        log.exception("file render failed")
        await call.message.answer("❌ Couldn't prepare the file.")
        return
    name = "".join(c if c.isalnum() else "_" for c in anime["title"])[:40] or "poster"
    await call.message.answer_document(BufferedInputFile(png, f"{name}_{key}{'_HD' if hd else ''}.png"))


@router.callback_query(F.data.startswith("f:"))
async def as_file(call: CallbackQuery, app: App) -> None:
    await _send_file(call, app, hd=False)


@router.callback_query(F.data.startswith("h:"))
async def as_hd_file(call: CallbackQuery, app: App) -> None:
    await _send_file(call, app, hd=True)


_PREVIEWING: set[int] = set()


@router.callback_query(F.data.startswith("pv:"))
async def preview_all(call: CallbackQuery, app: App) -> None:
    """One picture with every design side by side, numbered. Tapping a number turns that picture into the banner."""
    _, uid, mid, _key = call.data.split(":")
    uid_i, mid_i = int(uid), int(mid)
    if call.from_user.id != uid_i:
        await call.answer("Only the person who made this can use it.", show_alert=True)
        return
    if uid_i in _PREVIEWING:
        await call.answer("Still rendering your previews…")
        return
    _PREVIEWING.add(uid_i)
    await call.answer("Rendering every design, about 10 seconds…")
    status = await call.message.answer("⏳ Rendering every design…")
    try:
        grid, shown = await app.preview_grid(uid_i, mid_i)
        missing_special = any(t.special for t in app.templates) and not any(t.special for t in shown)
        await guard_icons(lambda: call.message.answer_photo(
            BufferedInputFile(grid, "designs.jpg"), caption=grid_caption(shown, missing_special), parse_mode="HTML",
            reply_markup=grid_kb(uid_i, mid_i, shown)))
        await status.delete()
    except RateLimited as e:
        await status.edit_text(f"⏳ Slow down a little: try again in {e.retry_after:.0f}s.")
    except Exception:
        log.exception("preview grid failed")
        await status.edit_text("❌ Couldn't build the preview. Try again in a moment.")
    finally:
        _PREVIEWING.discard(uid_i)
