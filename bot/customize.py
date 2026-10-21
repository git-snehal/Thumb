"""Customize panels: brand (text/logo/corner/font) and the Special Design (character, colors).
Every change re-renders the banner in place, so people see the result immediately."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaPhoto, Message

from . import artimg, cutout, fonts, schemes
from .app import BUSY, App, RateLimited, guard_icons
from .keyboards import (EDIT_ACTIONS, EDIT_LABELS, bg_kb, bg_text, caption, char_kb, char_text, edit_kb, edit_text_view, title_kb, title_text, colors_kb, colors_text, font_kb, panel_kb, panel_text,
                        pos_text, position_kb, template_kb)
from .style import POSITIONS

log = logging.getLogger(__name__)
router = Router()

MAX_BRAND_CHARS = 32
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
_CUTOUT_LOCK = asyncio.Semaphore(1)          # AI cutout is CPU heavy: one at a time

CHARACTER_PROMPT = (
    "✨ <b>Special Design</b>\n\n"
    "Send me the <b>character image</b> to put in the middle.\n\n"
    "• <b>Best:</b> a transparent PNG. Send it as a <i>file</i> (not as a photo) so Telegram keeps the transparency.\n"
    "• A normal image works too. I'll try to remove the background automatically.\n\n"
    "/cancel to stop."
)


class Wait(StatesGroup):
    text = State()
    logo = State()
    character = State()
    colors = State()
    background = State()
    title = State()
    edit = State()


ALL_WAIT = (Wait.text, Wait.logo, Wait.character, Wait.colors, Wait.background, Wait.title, Wait.edit)


def _ctx(data: str) -> tuple[int, int, str, str]:
    _, uid, mid, key, action = data.split(":", 4)
    return int(uid), int(mid), key, action


async def _effective(app: App, uid: int):
    s = await app.store.get(uid)
    return s, (s.position or app.cfg.brand_position), fonts.get(s.font).key


async def _view(app: App, uid: int, mid: int, key: str, view: str):
    """(caption text, keyboard factory) for one panel view."""
    s, pos, font = await _effective(app, uid)
    if view == "colors":
        anime = await app.cache.get(mid)
        cur = s.scheme or schemes.DEFAULT
        return colors_text(schemes.resolve(cur, anime["accent"])["label"]), (lambda: colors_kb(uid, mid, key, cur))
    if view == "bg":
        anime = await app.cache.get(mid)
        art = await app.store.get_art(uid, mid)
        if key == "special":        # the special design only uses these for its two Next cards
            n = len(anime.get("tmdb_urls") or [])
            label = "TMDB images" if n and art["idx"] >= 0 else "AniList images"
            return bg_text(label, False, n, True), (lambda: bg_kb(uid, mid, key, False, n, art["idx"], True))
        label, has_custom, n = await app.art_label(uid, anime)
        return bg_text(label, has_custom, n), (lambda: bg_kb(uid, mid, key, has_custom, n, art["idx"]))
    if view == "edt":
        anime = await app.cache.get(mid)
        ed = await app.store.get_edits(uid, mid)
        return edit_text_view(ed, anime), (lambda: edit_kb(uid, mid, key, ed))
    if view == "ttl":
        t = await app.store.get_title(uid, mid)
        return title_text(t), (lambda: title_kb(uid, mid, key, t))
    if view == "char":
        ch = await app.store.get_character(uid, mid)
        return char_text(ch), (lambda: char_kb(uid, mid, key))
    lpos = s.logo_position or app.cfg.logo_position
    if view == "pos":
        return pos_text("text", pos), (lambda: position_kb(uid, mid, key, pos, "text"))
    if view == "lpos":
        return pos_text("logo", lpos), (lambda: position_kb(uid, mid, key, lpos, "logo"))
    text = panel_text(s, app.cfg.brand_name, app.cfg.brand_position, app.cfg.logo_position)
    kbs = {
        "menu": lambda: panel_kb(uid, mid, key, mid == 0),
        "font": lambda: font_kb(uid, mid, key, font),
    }
    return text, kbs[view]


async def _edit(message: Message, text: str, kb) -> None:
    """Edit caption (banner) or text (standalone panel) in place."""
    try:
        if message.photo:
            await guard_icons(lambda: message.edit_caption(caption=text, parse_mode="HTML", reply_markup=kb()))
        else:
            await guard_icons(lambda: message.edit_text(text, parse_mode="HTML", reply_markup=kb()))
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            raise


async def _redraw(bot: Bot, app: App, chat_id: int, message_id: int, uid: int, mid: int, key: str,
                  text: str, kb) -> None:
    """Re-render the banner with the user's current choices and swap it into the message."""
    spec = app.spec(key) or app.templates[0]
    _, img = await app.render(mid, spec, uid)
    await guard_icons(lambda: bot.edit_message_media(
        media=InputMediaPhoto(media=BufferedInputFile(img, "poster.jpg"), caption=text, parse_mode="HTML"),
        chat_id=chat_id, message_id=message_id, reply_markup=kb(),
    ))


async def _show(bot: Bot, app: App, chat_id: int, message: Message | None, message_id: int,
                uid: int, mid: int, key: str, view: str = "menu", rerender: bool = False) -> None:
    text, kb = await _view(app, uid, mid, key, view)
    if mid and rerender:
        await _redraw(bot, app, chat_id, message_id, uid, mid, key, text, kb)
    elif message is not None:
        await _edit(message, text, kb)
    else:
        await guard_icons(lambda: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id,
                                                        parse_mode="HTML", reply_markup=kb()))


async def ask_character(msg: Message, state: FSMContext, uid: int, mid: int, key: str) -> None:
    """Prompt for the character image; the upload handler below picks it up."""
    await state.set_state(Wait.character)
    prompt = await msg.answer(CHARACTER_PROMPT, parse_mode="HTML")
    await state.update_data(chat=msg.chat.id, msg=msg.message_id, mid=mid, key=key, prompt=prompt.message_id)


# --------------------------------------------------------------------------- /settings
@router.message(Command("settings"))
async def settings_cmd(message: Message, app: App) -> None:
    uid = message.from_user.id
    s = await app.store.get(uid)
    await guard_icons(lambda: message.answer(
        panel_text(s, app.cfg.brand_name, app.cfg.brand_position, app.cfg.logo_position),
        parse_mode="HTML", reply_markup=panel_kb(uid, 0, "-", True)))


# --------------------------------------------------------------------------- buttons
@router.callback_query(F.data.startswith("c:"))
async def on_panel(call: CallbackQuery, app: App, bot: Bot, state: FSMContext) -> None:
    uid, mid, key, action = _ctx(call.data)
    if call.from_user.id != uid:
        await call.answer("This panel belongs to someone else.", show_alert=True)
        return
    msg = call.message
    ref = (msg.chat.id, msg.message_id)
    if ref in BUSY:
        await call.answer("Still rendering, one moment…")
        return

    if action == "close":
        await call.answer()
        await msg.delete()
        return

    if action == "back":                      # back to the banner view
        await call.answer()
        anime = await app.cache.get(mid)
        await _edit(msg, caption(anime["title"], key), lambda: template_kb(uid, mid, app.templates, key))
        return

    if action in ("txt", "logo", "colhex", "crep", "bgup", "ttlset") or action in EDIT_ACTIONS:
        await call.answer()
        if action == "crep":
            await ask_character(msg, state, uid, mid, key)
            return
        texts = {
            "txt": (Wait.text, f"✏️ <b>Send your brand text</b> (up to {MAX_BRAND_CHARS} characters).\n/cancel to stop."),
            "logo": (Wait.logo, "🖼 <b>Send your logo as a PNG file</b> (attach it as a <i>file/document</i> to keep "
                                "transparency; a normal photo works too but loses transparency).\n/cancel to stop."),
            "bgup": (Wait.background, "🌄 <b>Send the background image.</b> Attach it as a <i>file</i> to keep full quality "
                                      "(wide 16:9 images look best). It will be used on Template 1 and Posters 2 to 10 "
                                      "for this anime.\n/cancel to stop."),
            "colhex": (Wait.colors, "🎨 <b>Send 1 to 4 hex colors</b>, top to bottom, for example "
                                    "<code>#1d2b64 #7b2d8b #f8cdda</code>. With 3 or 4 colors the background fades through "
                                    "each one in turn. Light colors are darkened a little so the white text stays readable.\n/cancel to stop."),
            "ttlset": (Wait.title, "✏️ <b>Send the title, one line per row.</b> The first line is the big one, the next "
                                   "line(s) are small (up to 3 lines). Example:\n\n<code>Chitose Is in the Ramune Bottle\n2nd Cour</code>\n\n"
                                   "Send BOTH lines in ONE message (Shift+Enter makes a new line on desktop; on the phone the Enter key does).\n"
                                   "A long line has to fit the poster's height, so it can't be huge; shorter lines go bigger. "
                                   "Afterwards every line gets its own size and up/down buttons.\n/cancel to stop."),
        }
        if action in EDIT_ACTIONS:
            field = EDIT_ACTIONS[action]
            anime = await app.cache.get(mid)
            prompts = {
                "synopsis": "📝 <b>Send the new synopsis</b> (up to 600 characters).",
                "genres": "🏷 <b>Send the genres, separated by commas</b> (up to 4), for example <code>Action, Comedy, Fantasy</code>.",
                "season_line": "📅 <b>Send the season line</b>, for example <code>Fall 2026</code> or <code>2nd Cour • Fall 2026</code>.",
                "episodes_label": "🎞 <b>Send the episode label</b>, for example <code>11 episodes</code> or <code>Ep 13-24</code>.",
            }
            original = {"synopsis": anime.get("description", ""), "genres": ", ".join(anime.get("genres4") or []),
                        "season_line": anime.get("season_line", ""), "episodes_label": anime.get("episodes_label", "")}[field]
            shown_orig = original if len(original) < 160 else original[:157] + "…"
            await state.set_state(Wait.edit)
            prompt = await msg.answer(f"{prompts[field]}\nAniList says: <i>{shown_orig or '—'}</i>\n"
                                      "Send <code>-</code> to go back to the original.\n/cancel to stop.", parse_mode="HTML")
            await state.update_data(chat=msg.chat.id, msg=msg.message_id, mid=mid, key=key, prompt=prompt.message_id, field=field)
            return
        st, text = texts[action]
        await state.set_state(st)
        prompt = await msg.answer(text, parse_mode="HTML")
        await state.update_data(chat=msg.chat.id, msg=msg.message_id, mid=mid, key=key, prompt=prompt.message_id)
        return

    # everything below changes a setting (or just navigates) and may re-render the banner
    BUSY.add(ref)
    try:
        show = lambda view, rerender=False: _show(bot, app, msg.chat.id, msg, msg.message_id, uid, mid, key, view, rerender)
        if action in ("menu", "pos", "lpos", "font"):
            await call.answer()
            await show(action)
        elif action in ("colors", "char", "bg"):
            await call.answer()
            await show(action)
        elif action == "bgnext":
            anime = await app.cache.get(mid)
            n = len(anime.get("tmdb_urls") or [])
            if not n:
                await call.answer("No TMDB images for this one.", show_alert=True)
            else:
                cur = (await app.store.get_art(uid, mid))["idx"]
                nxt = 0 if cur < 0 else (cur + 1) % n          # TMDB images in turn; from AniList art go back to the first
                await call.answer("Loading image…")
                await app.store.set_art_idx(uid, mid, nxt)
                await show("bg", True)
        elif action == "bganilist":
            anime = await app.cache.get(mid)
            cur = (await app.store.get_art(uid, mid))["idx"]
            nxt = -2 if (cur == -1 and anime.get("banner")) else -1     # TMDB -> cover -> banner -> cover ...
            await call.answer("AniList banner" if nxt == -2 else "AniList cover")
            await app.store.set_art_idx(uid, mid, nxt)
            await show("bg", True)
        elif action == "ttl":
            await call.answer()
            await show("ttl")
        elif action == "edt":
            await call.answer()
            await show("edt")
        elif action == "edreset":
            await call.answer("Text reset")
            await app.store.clear_edits(uid, mid)
            await show("edt", True)
        elif action == "col_char":
            ch = await app.store.get_character(uid, mid)
            if not ch:
                await call.answer("Add a character first.", show_alert=True)
            else:
                raw = await asyncio.to_thread(Path(ch["path"]).read_bytes)
                value = await asyncio.to_thread(schemes.from_image, raw)
                if not value:
                    await call.answer("That picture has no clear colors to use.", show_alert=True)
                else:
                    await call.answer("Colors taken from your character")
                    await app.store.update(uid, scheme=value)
                    await show("colors", True)
        elif action == "ttlauto":
            await call.answer("Automatic title")
            await app.store.clear_title(uid, mid)
            await show("ttl", True)
        elif action in ("tgm", "tgp", "tswap") or action[:4] in ("tszm", "tszp") or action[:3] in ("tup", "tdn"):
            line, d_gap, d_size, d_shift, swap = None, 0, 0.0, 0, False
            if action == "tgm":
                d_gap = -6
            elif action == "tgp":
                d_gap = 6
            elif action == "tswap":
                swap = True
            elif action[:4] in ("tszm", "tszp"):                 # tszm2 = line 2 smaller, tszp1 = line 1 bigger
                line, d_size = int(action[4]) - 1, (-0.1 if action[3] == "m" else 0.1)
            else:                                                # tup1 / tdn3 = move that line up / down
                line, d_shift = int(action[3]) - 1, (-30 if action[:3] == "tup" else 30)
            if not await app.store.adjust_title(uid, mid, d_gap, line, d_size, d_shift, swap):
                await call.answer("Set a title first.", show_alert=True)
            else:
                await call.answer()
                await show("ttl", True)
        elif action == "bgdel":
            await call.answer("Removed")
            await app.store.remove_background(uid, mid)
            await show("bg", True)
        elif action.startswith("sp") and action[2:] in POSITIONS:
            await call.answer("Moving brand…")
            await app.store.update(uid, position=action[2:])
            await show("pos", True)
        elif action.startswith("sl") and action[2:] in POSITIONS:
            await call.answer("Moving logo…")
            await app.store.update(uid, logo_position=action[2:])
            await show("lpos", True)
        elif action.startswith("sf") and action[2:] in fonts.FONTS:
            await call.answer(f"Font: {fonts.FONTS[action[2:]].label}")
            await app.store.update(uid, font=action[2:])
            await show("font", True)
        elif action == "off":
            await call.answer("Brand removed")
            await app.store.remove_brand(uid)
            await show("menu", True)
        elif action.startswith("col_") and (action[4:] in schemes.PRESETS or action[4:] == schemes.AUTO):
            await call.answer("Applying colors…")
            await app.store.update(uid, scheme=action[4:])
            await show("colors", True)
        elif action in ("cplus", "cminus", "cleft", "cright"):
            step = {"cplus": (0, .08), "cminus": (0, -.08), "cleft": (-40, 0), "cright": (40, 0)}[action]
            if not await app.store.adjust_character(uid, mid, *step):
                await call.answer("Send a character first.", show_alert=True)
            else:
                await call.answer()
                await show("char", True)
        else:
            await call.answer()
    except RateLimited as e:
        await msg.answer(f"⏳ Slow down a little: try again in {e.retry_after:.0f}s.")
    except Exception:
        log.exception("customize failed")
        await msg.answer("❌ Couldn't apply that. Try again.")
    finally:
        BUSY.discard(ref)


# --------------------------------------------------------------------------- conversation inputs
async def _tidy(bot: Bot, message: Message, *ids: int | None) -> None:
    for mid_ in (*ids, message.message_id):
        if mid_:
            try:
                await bot.delete_message(message.chat.id, mid_)
            except TelegramBadRequest:
                pass


async def _finish_input(bot: Bot, app: App, message: Message, state: FSMContext, uid: int, view: str = "menu") -> None:
    """Tidy the prompt + the user's message, then refresh the panel they started from."""
    d = await state.get_data()
    await state.clear()
    await _tidy(bot, message, d.get("prompt"))
    try:
        await _show(bot, app, d["chat"], None, d["msg"], uid, d["mid"], d["key"], view, rerender=True)
    except Exception:
        log.exception("refresh after input failed")
        await message.answer("✅ Saved. Open the panel again to see it.")


@router.message(Command("cancel"), StateFilter(*ALL_WAIT))
async def cancel(message: Message, state: FSMContext, bot: Bot) -> None:
    d = await state.get_data()
    await state.clear()
    if d.get("prompt"):
        try:
            await bot.delete_message(message.chat.id, d["prompt"])
        except TelegramBadRequest:
            pass
    await message.answer("Cancelled.")


@router.message(Wait.text, F.text, ~F.text.startswith("/"))
async def got_text(message: Message, app: App, bot: Bot, state: FSMContext) -> None:
    text = " ".join(message.text.split())[:MAX_BRAND_CHARS]
    await app.store.update(message.from_user.id, brand_text=text, brand_off=0)
    await _finish_input(bot, app, message, state, message.from_user.id)


EDIT_LIMITS = {"synopsis": 600, "genres": 90, "season_line": 40, "episodes_label": 30}


@router.message(Wait.edit, F.text, ~F.text.startswith("/"))
async def got_edit(message: Message, app: App, bot: Bot, state: FSMContext) -> None:
    d = await state.get_data()
    field = d["field"]
    text = " ".join(message.text.split())
    if text == "-":
        value = None                                              # back to AniList's original
    elif field == "genres":
        parts = [p.strip()[:22] for p in text.split(",") if p.strip()][:4]
        if not parts:
            await message.answer("Send at least one genre, like <code>Action, Comedy</code>, or /cancel.", parse_mode="HTML")
            return
        value = ", ".join(parts)
    else:
        if len(text) > EDIT_LIMITS[field]:
            await message.answer(f"That's {len(text)} characters; the limit for this field is {EDIT_LIMITS[field]}. Shorten it, or /cancel.")
            return
        value = text
    await app.store.set_edit(message.from_user.id, d["mid"], field, value)
    await _finish_input(bot, app, message, state, message.from_user.id, view="edt")


@router.message(Wait.title, F.text, ~F.text.startswith("/"))
async def got_title(message: Message, app: App, bot: Bot, state: FSMContext) -> None:
    lines = [" ".join(ln.split())[:60] for ln in message.text.splitlines()]
    lines = [ln for ln in lines if ln][:3]
    if not lines:
        await message.answer("Send at least one line of text, or /cancel.")
        return
    d = await state.get_data()
    await app.store.set_title(message.from_user.id, d["mid"], lines)
    await _finish_input(bot, app, message, state, message.from_user.id, view="ttl")
    if len(lines) == 1:
        await message.answer("ℹ️ I only received one line. For a small second line, tap Set title again and send both "
                             "lines in one message (Shift+Enter for a new line on desktop).")


@router.message(Wait.colors, F.text, ~F.text.startswith("/"))
async def got_colors(message: Message, app: App, bot: Bot, state: FSMContext) -> None:
    too_many = schemes.count_colors(message.text) > schemes.MAX_COLORS
    value = schemes.parse_custom(message.text)
    if not value:
        await message.answer("I couldn't find a hex color in that. Try like <code>#1d2b64 #7b2d8b #f8cdda</code>, or /cancel.",
                             parse_mode="HTML")
        return
    await app.store.update(message.from_user.id, scheme=value)
    await _finish_input(bot, app, message, state, message.from_user.id, view="colors")
    if too_many:
        await message.answer(f"ℹ️ A gradient can have up to {schemes.MAX_COLORS} colors, so I used the first {schemes.MAX_COLORS}.")


async def _download_image(message: Message, bot: Bot):
    """Return the uploaded image's bytes, or None after telling the user what's wrong."""
    doc = message.document
    if doc and not (doc.mime_type or "").startswith("image/"):
        await message.answer("That isn't an image. Send a PNG or JPG (or /cancel).")
        return None
    target = doc or message.photo[-1]
    if (target.file_size or 0) > MAX_UPLOAD_BYTES:
        await message.answer("That file is over 12 MB. Send a smaller one.")
        return None
    return (await bot.download(target)).getvalue()


@router.message(Wait.logo, F.document | F.photo)
async def got_logo(message: Message, app: App, bot: Bot, state: FSMContext) -> None:
    raw = await _download_image(message, bot)
    if raw is None:
        return
    try:
        await app.store.save_logo(message.from_user.id, raw)
    except Exception:
        log.exception("bad logo")
        await message.answer("I couldn't read that image. Try a PNG file, or /cancel.")
        return
    await _finish_input(bot, app, message, state, message.from_user.id)


NOTES = {
    "ai": "✂️ Background removed automatically. If the edges look rough, send a transparent PNG instead.",
    "flat": "✂️ Removed the plain background. A transparent PNG will always look cleaner.",
    "opaque": "⚠️ I couldn't remove that background, so the image keeps its box. "
              "For the best result send a transparent PNG (as a file).",
}


@router.message(Wait.background, F.document | F.photo)
async def got_background(message: Message, app: App, bot: Bot, state: FSMContext) -> None:
    raw = await _download_image(message, bot)
    if raw is None:
        return
    d = await state.get_data()
    try:
        jpeg, wide = await asyncio.to_thread(artimg.prepare_background, raw)
    except Exception:
        log.exception("bad background image")
        await message.answer("I couldn't use that image. Send a JPG or PNG that's at least 200px, or /cancel.")
        return
    await app.store.save_background(message.from_user.id, d["mid"], jpeg, wide)
    await _finish_input(bot, app, message, state, message.from_user.id, view="bg")
    if not wide:
        await message.answer("ℹ️ That image is portrait-shaped, so full-bleed designs will crop it. A wide 16:9 image fits best.")


@router.message(Wait.character, F.document | F.photo)
async def got_character(message: Message, app: App, bot: Bot, state: FSMContext) -> None:
    uid = message.from_user.id
    raw = await _download_image(message, bot)
    if raw is None:
        return
    status = await message.answer("✂️ Preparing your character…")
    try:
        async with _CUTOUT_LOCK:
            png, mode = await asyncio.to_thread(cutout.prepare, raw, app.cfg.auto_cutout)
    except Exception:
        log.exception("bad character image")
        await status.edit_text("I couldn't read that image. Try a PNG or JPG, or /cancel.")
        return

    d = await state.get_data()
    await state.clear()
    await app.store.save_character(uid, d["mid"], png)
    await _tidy(bot, message, d.get("prompt"), status.message_id)
    try:
        anime = await app.cache.get(d["mid"])
        await _redraw(bot, app, d["chat"], d["msg"], uid, d["mid"], "special",
                      caption(anime["title"], "special"), lambda: template_kb(uid, d["mid"], app.templates, "special"))
    except Exception:
        log.exception("special render failed")
        await message.answer("❌ Saved your character but couldn't render it. Tap Special Design again.")
        return
    if note := NOTES.get(mode):
        await message.answer(note)


@router.message(StateFilter(*ALL_WAIT))
async def wrong_input(message: Message) -> None:
    await message.answer("I'm waiting for what I asked for just above — send it, or /cancel.")
