"""Offline end-to-end test: fake AniList + fake Telegram, real handlers, real Chromium, real SQLite."""
from __future__ import annotations

import asyncio
import io
import json
import tempfile
from datetime import datetime
from pathlib import Path

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Chat, Document, File, Message, MessageEntity, Update, User
from PIL import Image

from bot import icons, texts
from bot.anilist import AniList
from bot.app import App
from bot.assets import AnimeCache
from bot.config import ROOT, Config
from bot.customize import router as customize_router
from bot.handlers import _COOLDOWN, router as anime_router
from bot.registry import load_templates
from bot.render import Renderer
from bot.start import router as start_router
from bot.store import Store
from bot.tmdb import TMDB, TMDBError
from bot.style import Style
from bot import instance
from bot.app import RateLimited, apply_edits
from bot.guard import AllowListMiddleware, RateLimiter


def png(w, h, color, alpha=255):
    b = io.BytesIO()
    Image.new("RGBA", (w, h), (*color, alpha)).save(b, "PNG")
    return b.getvalue()


MEDIA = {
    "id": 163134, "siteUrl": "x",
    "title": {"romaji": "Alya-san", "english": "Alya Sometimes Hides Her Feelings in Russian", "native": "x"},
    "description": "Alya is a transfer student.<br><br>She ignores Kuze.<br>(Source: Crunchyroll)",
    "format": "TV", "status": "FINISHED", "season": "SUMMER", "seasonYear": 2024, "episodes": 12, "duration": 24,
    "averageScore": 79, "genres": ["Comedy", "Romance", "Slice of Life", "Drama"],
    "bannerImage": "https://img.test/banner.png",
    "coverImage": {"extraLarge": "https://img.test/cover.png", "large": "https://img.test/cover.png", "color": "#e4a1a1"},
    "studios": {"nodes": [{"name": "Doga Kobo"}]},
    "characters": {"edges": [
        {"role": "MAIN", "node": {"name": {"full": "Alisa Mikhailovna Kujou"}, "image": {"large": "https://img.test/c1.png"}},
         "voiceActors": [{"name": {"full": "Sayumi Watabe"}, "image": {"large": "https://img.test/v1.png"}}]}]},
    "streamingEpisodes": [],
}


def fake_web(request: httpx.Request) -> httpx.Response:
    if request.url.host == "graphql.anilist.co":
        q = json.loads(request.content)["query"]
        if "Page(" in q:
            return httpx.Response(200, json={"data": {"Page": {"media": [
                {"id": 163134, "title": MEDIA["title"], "seasonYear": 2024, "format": "TV"}]}}})
        return httpx.Response(200, json={"data": {"Media": MEDIA}})
    if request.url.host == "api.themoviedb.org":
        path, q = request.url.path, request.url.params
        if path == "/3/search/tv":
            if "Totally Different" in q.get("query", ""):
                return httpx.Response(200, json={"results": [{"id": 5, "name": "Naruto", "first_air_date": "2002-10-03", "genre_ids": [16]}]})
            return httpx.Response(200, json={"results": [
                {"id": 99, "name": "Some Other Show", "first_air_date": "2010-01-01", "genre_ids": [18]},
                {"id": 111, "name": "Alya Sometimes Hides Her Feelings in Russian", "first_air_date": "2024-07-01", "genre_ids": [16, 35]}]})
        if path == "/3/search/movie":
            return httpx.Response(200, json={"results": []})
        if path == "/3/tv/111/images":
            return httpx.Response(200, json={"backdrops": [
                {"file_path": "/third.jpg", "width": 1920, "iso_639_1": "en", "vote_average": 9},
                {"file_path": "/best.jpg", "width": 3840, "iso_639_1": None, "vote_average": 5},
                {"file_path": "/second.jpg", "width": 1920, "iso_639_1": None, "vote_average": 4},
                {"file_path": "/tiny.jpg", "width": 900, "iso_639_1": None, "vote_average": 10}]})
        return httpx.Response(404, json={})
    if request.url.host == "image.tmdb.org":
        if "/t/p/original/" in request.url.path:
            return httpx.Response(200, content=png(3200, 1800, (60, 110, 180)), headers={"content-type": "image/png"})
        return httpx.Response(200, content=png(1280, 720, (40, 90, 160)), headers={"content-type": "image/png"})
    return httpx.Response(200, content=png(400, 600, (136, 153, 204)), headers={"content-type": "image/png"})


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.reject_icons = False
        self.stream_bytes = png(300, 120, (255, 0, 0), alpha=140)   # what the next uploaded file contains

    async def close(self): ...

    async def stream_content(self, *a, **k):
        yield self.stream_bytes

    async def make_request(self, bot, method, timeout=None):
        name = type(method).__name__
        markup = getattr(method, "reply_markup", None)
        if self.reject_icons and markup and any(
                b.icon_custom_emoji_id for row in markup.inline_keyboard for b in row):
            raise TelegramBadRequest(method=method, message="Bad Request: custom emoji icon not allowed")
        self.calls.append(method)
        if name == "GetFile":
            return File(file_id="f", file_unique_id="u", file_path="logo.png").as_(bot)
        if name in ("SendMessage", "SendPhoto", "SendDocument", "EditMessageMedia", "EditMessageText", "EditMessageCaption"):
            return Message(message_id=500 + len(self.calls), date=datetime.now(), chat=Chat(id=1, type="private")).as_(bot)
        return True

    def names(self):
        return [type(c).__name__ for c in self.calls]


def datas(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]


async def main():
    tmp = Path(tempfile.mkdtemp())
    cfg = Config(bot_token="1:fake", brand_name="", brand_position="tr", fancy_text=True, auto_cutout=False, icons={},
                 render_concurrency=2, cache_ttl=60, db_path=tmp / "bot.db", logos_dir=tmp / "logos")
    texts.FANCY = True
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake_web))
    al = AniList(http)
    renderer = Renderer(ROOT / "templates", ROOT / "assets", 2)
    tm = TMDB(http, "k" * 32)
    app = App(cfg, al, AnimeCache(al, http, 60, tmdb=tm), renderer, load_templates(), Store(cfg.db_path, cfg.logos_dir))
    session = FakeSession()
    bot = Bot("1:fake", session=session)
    dp = Dispatcher()
    dp.include_routers(customize_router, anime_router, start_router)
    dp["app"] = app
    user = User(id=42, is_bot=False, first_name="Snehal")
    chat = Chat(id=1, type="private")
    n = [0]

    async def send(text=None, **kw):
        n[0] += 1
        ents = None
        if text and text.startswith("/"):
            ents = [MessageEntity(type="bot_command", offset=0, length=len(text.split()[0]))]
        m = Message(message_id=10 + n[0], date=datetime.now(), chat=chat, from_user=user, text=text,
                    entities=kw.pop("entities", ents), **kw)
        session.calls.clear()
        _COOLDOWN.clear()
        await dp.feed_update(bot, Update(update_id=n[0], message=m))

    bot_msg = Message(message_id=900, date=datetime.now(), chat=chat, from_user=User(id=1, is_bot=True, first_name="b"),
                      caption="banner", photo=[{"file_id": "p", "file_unique_id": "pu", "width": 1, "height": 1}])

    async def tap(data, who=user):
        n[0] += 1
        cb = CallbackQuery(id=str(n[0]), from_user=who, chat_instance="x", message=bot_msg, data=data)
        session.calls.clear()
        await dp.feed_update(bot, Update(update_id=n[0], callback_query=cb))

    # 1) animated /start
    import bot.start as st
    st_sleep = asyncio.sleep
    asyncio.sleep = lambda *_: st_sleep(0)         # skip the real delays in the test
    await send("/start")
    names = session.names()
    print("start:", names)
    assert names[0] == "SendMessage" and names.count("EditMessageText") >= 4, names
    final = session.calls[-1]
    assert "ʜᴇʟʟᴏ" in final.text and "Snehal" in final.text and "<blockquote>" in final.text
    assert "go" in datas(final.reply_markup) and "help" in datas(final.reply_markup)
    asyncio.sleep = st_sleep

    # 2) /anime -> banner
    await send("/poster alya")       # /anime and /thumb still work as aliases
    photo = next(c for c in session.calls if type(c).__name__ == "SendPhoto")
    d = datas(photo.reply_markup)
    print("banner buttons:", len(d), "| styled:", photo.reply_markup.inline_keyboard[0][0].text)
    assert any(x.startswith("c:42:163134:template1:menu") for x in d) and any(x.startswith("f:") for x in d)
    assert sum(x.startswith("t:") for x in d) == 13, "13 templates expected (12 + special)"
    assert any(x.startswith("t:42:163134:special") for x in d)
    assert len(photo.photo.data) > 20_000

    # 3) switch to new Poster 8, then others are refused
    await tap("t:42:163134:animeposter8")
    assert "EditMessageMedia" in session.names()
    await tap("t:42:163134:animeposter3", who=User(id=7, is_bot=False, first_name="x"))
    assert session.calls[0].show_alert

    # 4) position + font change re-render live and persist
    await tap("c:42:163134:template1:menu")
    assert "EditMessageCaption" in session.names()
    await tap("c:42:163134:template1:spbr")
    assert "EditMessageMedia" in session.names()
    await tap("c:42:163134:template1:sfbebas")
    assert "EditMessageMedia" in session.names()
    s = await app.store.get(42)
    print("saved:", s)
    assert s.position == "br" and s.font == "bebas"

    # 5) brand text via the conversation flow
    await tap("c:42:163134:template1:txt")
    assert "SendMessage" in session.names()
    await send("  My   Anime Hub ")
    assert "EditMessageMedia" in session.names() and "DeleteMessage" in session.names(), session.names()
    assert (await app.store.get(42)).brand_text == "My Anime Hub"
    st_style = await app.style_for(42)
    assert (st_style.brand_text, st_style.position, st_style.font) == ("My Anime Hub", "br", "bebas")

    # 6) logo upload (transparent PNG sent as a document)
    await tap("c:42:163134:template1:logo")
    await send(None, document=Document(file_id="f", file_unique_id="u", mime_type="image/png", file_size=500))
    s = await app.store.get(42)
    assert s.logo_path and Path(s.logo_path).is_file()
    logo = Image.open(s.logo_path)
    assert logo.mode == "RGBA" and logo.getpixel((5, 5))[3] == 140, "transparency must survive"
    assert (await app.style_for(42)).logo.startswith("data:image/png")
    print("logo saved with alpha OK")

    # 6b) logo and brand text have their OWN corners
    await tap("c:42:163134:template1:lpos")
    assert "EditMessageCaption" in session.names()
    await tap("c:42:163134:template1:sltr")
    assert "EditMessageMedia" in session.names()
    s = await app.store.get(42)
    assert (s.position, s.logo_position) == ("br", "tr"), s
    st_style = await app.style_for(42)
    assert (st_style.position, st_style.logo_position) == ("br", "tr")
    html = renderer.html("template1.html", await app.cache.get(163134), "", st_style)
    assert html.count('class="brand-ov') == 2, "text and logo in different corners -> two overlays"
    same = renderer.html("template1.html", await app.cache.get(163134), "", Style("Hub", st_style.logo, "tl", logo_position="tl"))
    assert same.count('class="brand-ov') == 1, "same corner -> stacked in one overlay"
    print("separate corners OK")

    # 7) wrong input while waiting, /cancel
    await tap("c:42:163134:template1:txt")
    await send("/cancel")
    assert session.calls[-1].text == "Cancelled."

    # 8) remove brand
    await tap("c:42:163134:template1:off")
    s = await app.store.get(42)
    assert s.brand_off and not s.logo_path
    assert (await app.style_for(42)).brand_text == ""

    # 9) standalone /settings
    await send("/settings")
    assert "SendMessage" in session.names() and "<blockquote>" in session.calls[0].text

    # 10) emoji ID helper
    await send("hi", entities=[MessageEntity(type="custom_emoji", offset=0, length=2, custom_emoji_id="5368324170671202286")])
    assert "5368324170671202286" in session.calls[0].text
    print("emojiid OK")


    # 10b) Special Design: asks for a character the first time
    await tap("t:42:163134:special")
    assert session.names() == ["AnswerCallbackQuery", "SendMessage"], session.names()
    assert "character image" in session.calls[1].text
    await send(None, document=Document(file_id="f", file_unique_id="u", mime_type="image/png", file_size=500))
    names = session.names()
    print("character upload:", names)
    assert "EditMessageMedia" in names, names
    ch = await app.store.get_character(42, 163134)
    assert ch and ch["scale"] == 1.0
    edit = next(c for c in session.calls if type(c).__name__ == "EditMessageMedia")
    kb = datas(edit.reply_markup)
    assert "c:42:163134:special:colors" in kb and "c:42:163134:special:char" in kb, kb
    assert "special" in edit.media.caption

    # colour schemes: open the menu, pick a preset, send custom hex (bad, then good)
    await tap("c:42:163134:special:colors")
    assert "EditMessageCaption" in session.names()
    await tap("c:42:163134:special:col_sunset")
    assert "EditMessageMedia" in session.names() and (await app.store.get(42)).scheme == "sunset"
    await tap("c:42:163134:special:colhex")
    await send("not a color")
    assert "couldn't find a hex" in session.calls[0].text
    await send("make it #112233 #445566 please")
    assert (await app.store.get(42)).scheme == "#112233,#445566" and "EditMessageMedia" in session.names()
    from bot import schemes as _sch
    assert _sch.resolve("#112233,#445566")["label"] == "Custom"

    # character nudging
    await tap("c:42:163134:special:cplus")
    await tap("c:42:163134:special:cleft")
    ch = await app.store.get_character(42, 163134)
    print("character after nudge:", ch["dx"], ch["scale"])
    assert ch["scale"] == 1.08 and ch["dx"] == -40

    # tapping Special Design again re-uses the saved character (no prompt)
    await tap("t:42:163134:animeposter2")
    await tap("t:42:163134:special")
    assert "EditMessageMedia" in session.names() and "SendMessage" not in session.names()

    # replace with a NORMAL image: white plain background -> automatically removed
    flat = Image.new("RGB", (300, 400), (255, 255, 255))
    from PIL import ImageDraw as _D
    _D.Draw(flat).ellipse([80, 60, 220, 340], fill=(200, 40, 60))
    b = io.BytesIO(); flat.save(b, "PNG")
    session.stream_bytes = b.getvalue()
    await tap("c:42:163134:special:crep")
    assert "character image" in session.calls[1].text
    await send(None, document=Document(file_id="f", file_unique_id="u", mime_type="image/png", file_size=500))
    notes = [c.text for c in session.calls if type(c).__name__ == "SendMessage"]
    print("note:", notes)
    assert any("plain background" in t for t in notes)
    saved = Image.open((await app.store.get_character(42, 163134))["path"])
    assert saved.getpixel((0, 0))[3] < 30, "flat background should be transparent"
    session.stream_bytes = png(300, 120, (255, 0, 0), alpha=140)

    # cancel works for the character prompt too
    await tap("c:42:163134:special:crep")
    await send("/cancel")
    assert session.calls[-1].text == "Cancelled."

    # 11) animated icons are used when configured, and fall back if Telegram refuses them
    icons.configure({"template": "111", "customize": "222"})
    await send("/anime alya")
    photo = next(c for c in session.calls if type(c).__name__ == "SendPhoto")
    assert any(b.icon_custom_emoji_id == "111" for row in photo.reply_markup.inline_keyboard for b in row)
    print("icons attached OK")
    session.reject_icons = True
    n_before = len(session.calls)
    await send("/anime alya")
    photo = next(c for c in session.calls if type(c).__name__ == "SendPhoto")
    assert not any(b.icon_custom_emoji_id for row in photo.reply_markup.inline_keyboard for b in row)
    assert not icons.any_configured(), "icons should be disabled after a rejection"
    print("icon fallback OK")


    # 12) special design brand rules: built-in PNGs by default, user text overrides, removed brand hides them
    anime = await app.cache.get(163134)
    ch = {"src": "data:image/png;base64,AAAA", "dx": 0, "scale": 1}
    h = renderer.html("special.html", anime, "", Style("", None, "tr", scheme=None, char=ch))
    assert "special/watermark.png" in h and "special/credit.png" in h and "special/boxes.png" in h
    h = renderer.html("special.html", anime, "", Style("MY HUB TEAM", None, "tr", char=ch))
    assert 'class="credit"' in h and "special/watermark.png" not in h and "special/credit.png" not in h
    h = renderer.html("special.html", anime, "", Style("", None, "tr", char=ch, special_defaults=False))
    assert "special/watermark.png" not in h and "special/credit.png" not in h and "special/boxes.png" in h
    h = renderer.html("special.html", anime, "", Style("", None, "tr", char=ch))
    assert "opacity: 1.0;" in h.split(".boxes-img")[1].split("}")[0], "boxes default to pure white (no dulling opacity)"
    h = renderer.html("special.html", anime, "", Style("", None, "tr", char=ch, boxes_opacity=0.5))
    assert "opacity: 0.5;" in h.split(".boxes-img")[1].split("}")[0], "...and the setting changes it"
    print("special defaults OK")

    # 13) /version tells which copy answered; the stale-instance matcher
    await send("/version")
    assert "v2.0" in session.calls[0].text and "process" in session.calls[0].text
    assert instance.is_bot_cmdline(["/usr/bin/python3", "-m", "bot"]) and not instance.is_bot_cmdline(["python", "app.py"])
    await send("/help")
    assert "/poster" in session.calls[0].text and "/anime &lt;" not in session.calls[0].text and "/anime id" not in session.calls[0].text
    print("version/help OK")

    # 14) TMDB: ranking, art selection, fallbacks
    anime = await app.cache.get(163134)
    assert anime["tmdb_urls"] == ["/best.jpg", "/second.jpg", "/third.jpg"], anime["tmdb_urls"]   # no-text first, biggest first, tiny dropped
    meta = {"title_english": "Alya Sometimes Hides Her Feelings in Russian 2nd Cour", "title_romaji": "", "format_raw": "TV", "year": 2025}
    assert (await tm.find(meta))[1] == 111, "sequel title is cleaned before matching"
    assert await tm.find({"title_english": "Totally Different Show", "title_romaji": "", "format_raw": "TV", "year": 2024}) is None
    bad = TMDB(http, "k" * 32)
    async def boom(*a, **k): raise TMDBError("401")
    bad._get = boom
    assert await AnimeCache(al, http, 60, tmdb=bad)._tmdb_paths(anime) == [], "TMDB errors never break a banner"
    assert await AnimeCache(al, http, 60)._tmdb_paths(anime) == [], "no key -> no TMDB art"
    seen = []
    async def capture(request):
        seen.append(request)
    probe = TMDB(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (seen.append(r), httpx.Response(200, json={"results": []}))[1])), "k" * 32)
    await probe._get("/search/tv", query="x"); assert seen[-1].url.params["api_key"] == "k" * 32 and "authorization" not in seen[-1].headers
    long_key = TMDB(probe.http, "e" * 80)
    await long_key._get("/search/tv", query="x"); assert seen[-1].headers["authorization"].startswith("Bearer ") and "api_key" not in seen[-1].url.params
    print("tmdb OK")

    # 15) Background panel: TMDB images -> next image -> cover -> custom upload -> remove
    uri, wide = await app.art_for(42, anime)
    assert wide and uri.startswith("data:image/")
    await tap("c:42:163134:animeposter9:menu")
    kb = datas(next(c for c in session.calls if type(c).__name__ == "EditMessageCaption").reply_markup)
    assert "c:42:163134:animeposter9:bg" in kb, "Background button shown for normal posters"
    await tap("c:42:163134:special:menu")
    kb = datas(next(c for c in session.calls if type(c).__name__ == "EditMessageCaption").reply_markup)
    assert any(x.endswith(":bg") for x in kb), "...and shown for the special design (Next-card images)"
    await tap("c:42:163134:animeposter9:bg")
    cap = next(c for c in session.calls if type(c).__name__ == "EditMessageCaption")
    assert "TMDB image 1 of 3" in cap.caption and any(x.endswith(":bgnext") for x in datas(cap.reply_markup))
    order = []
    for _ in range(4):
        await tap("c:42:163134:animeposter9:bgnext")
        assert "EditMessageMedia" in session.names()
        order.append((await app.store.get_art(42, 163134))["idx"])
    assert order == [1, 2, 0, 1], order                       # TMDB images in turn, wrapping around
    await tap("c:42:163134:animeposter9:bganilist")           # AniList button: cover ...
    assert (await app.store.get_art(42, 163134))["idx"] == -1
    uri, wide = await app.art_for(42, anime)
    assert uri is None and not wide, "AniList cover selected"
    await tap("c:42:163134:animeposter9:bganilist")           # ... then banner ...
    assert (await app.store.get_art(42, 163134))["idx"] == -2
    uri, wide = await app.art_for(42, anime)
    assert uri == anime["banner"] and wide and (await app.art_label(42, anime))[0] == "AniList banner"
    await tap("c:42:163134:animeposter9:bganilist")           # ... then cover again
    assert (await app.store.get_art(42, 163134))["idx"] == -1
    await tap("c:42:163134:animeposter9:bgnext")              # Next image from AniList art returns to the first TMDB image
    assert (await app.store.get_art(42, 163134))["idx"] == 0
    jb = io.BytesIO(); Image.new("RGB", (1600, 900), (10, 120, 200)).save(jb, "JPEG")
    session.stream_bytes = jb.getvalue()
    await tap("c:42:163134:animeposter9:bgup")
    assert "background image" in session.calls[1].text.lower()
    await send(None, document=Document(file_id="f", file_unique_id="u", mime_type="image/jpeg", file_size=500))
    assert "EditMessageMedia" in session.names()
    art = await app.store.get_art(42, 163134)
    assert art["path"] and art["wide"]
    uri, wide = await app.art_for(42, anime)
    assert wide and uri.startswith("data:image/jpeg")
    assert (await app.art_label(42, anime))[0] == "your image"
    await tap("c:42:163134:animeposter9:bgdel")
    assert (await app.store.get_art(42, 163134))["path"] is None
    pb = io.BytesIO(); Image.new("RGB", (400, 600), (10, 120, 200)).save(pb, "JPEG")
    session.stream_bytes = pb.getvalue()
    await tap("c:42:163134:animeposter9:bgup")
    await send(None, document=Document(file_id="f", file_unique_id="u", mime_type="image/jpeg", file_size=500))
    assert any("portrait-shaped" in (c.text or "") for c in session.calls if type(c).__name__ == "SendMessage")
    await app.store.remove_background(42, 163134)
    session.stream_bytes = png(300, 120, (255, 0, 0), alpha=140)
    print("background panel OK")

    # 16) Special design: built-in defaults survive "Remove brand"; title is one line when it fits
    await app.store.remove_brand(42)
    assert (await app.style_for(42)).special_defaults is True
    sty = Style("", None, "tr", char=ch)
    cols = lambda a: renderer.inspect("special.html", a, "document.body.dataset.titleColumns", style=sty)
    assert await cols({**anime, "title": "One Piece", "title_big": "Piece", "title_small": "One"}) == "1"
    assert await cols({**anime, "title": "Bleach", "title_big": "Bleach", "title_small": ""}) == "1"
    assert await cols({**anime, "title": "That Time I Got Reincarnated as a Slime", "title_big": "Slime",
                       "title_small": "That Time I Got Reincarnated as a"}) == "2"
    print("title columns OK")
    await send("/version")
    assert "special defaults: on" in session.calls[0].text and "TMDB art: on" in session.calls[0].text

    # 17) special design: distinct Next cards, aligned studio block, full-width watermark
    await app.store.set_art_idx(42, 163134, 0)
    nxt = await app.next_images(42, anime)
    assert len(nxt) == 2 and "/second.jpg" in app.cache._imgs and "/third.jpg" in app.cache._imgs, "TMDB: the next two scenes"
    await app.store.set_art_idx(42, 163134, -1)
    nxt = await app.next_images(42, anime)
    assert nxt == [anime["banner"], anime["cover"]], "AniList chosen: banner then cover"
    await app.store.set_art_idx(42, 163134, 0)
    await tap("c:42:163134:special:bg")
    cap = next(c for c in session.calls if type(c).__name__ == "EditMessageCaption")
    d_ = datas(cap.reply_markup)
    assert "next-card images" in cap.caption.lower() or "ɴᴇxᴛ-ᴄᴀʀᴅ" in cap.caption
    assert any(x.endswith(":bgnext") for x in d_) and any(x.endswith(":bganilist") for x in d_) and not any(x.endswith(":bgup") for x in d_)
    h = renderer.html("special.html", anime, "", Style("", None, "tr", char=ch))
    assert 'class="act"' in h and "left: 0; bottom: -44px; width: 1280px" in h
    print("special layout OK")

    # 18) gradients with 3 and 4 colours
    for text, count in (("#112233 #445566 #778899", 3), ("#112233 #445566 #778899 #aabbcc", 4)):
        res = _sch.resolve(_sch.parse_custom(text))
        assert len(res["stops"]) == count
        h = renderer.html("special.html", anime, "", Style("", None, "tr", scheme=res, char=ch))
        assert "linear-gradient(180deg, #" in h and "100%" in h, "stops are written into the gradient"
    assert len(_sch.parse_custom("#111111 #222222 #333333 #444444 #555555 #666666").split(",")) == 4
    await tap("c:42:163134:special:colhex")
    await send("#102030 #405060 #708090 #a0b0c0 #d0e0f0 #ffffff")
    assert (await app.store.get(42)).scheme.count("#") == 4
    assert any("up to 4 colors" in (c.text or "") for c in session.calls if type(c).__name__ == "SendMessage")
    print("multi-colour gradients OK")

    # 19) typed title: natural order (line 1 = right column), per-line size and position, swap, single line grows
    import json as _j
    probe = ("JSON.stringify({sizes: JSON.parse(document.body.dataset.titleSizes), cols: [...document.querySelectorAll('#vtc > div')]"
             ".map(d => ({line: +d.dataset.i + 1, x: Math.round(d.getBoundingClientRect().left), y: Math.round(d.getBoundingClientRect().top)}))"
             ".sort((p, q) => p.x - q.x).map(c => c.line), ys: [...document.querySelectorAll('#vtc > div')]"
             ".sort((p, q) => +p.dataset.i - +q.dataset.i).map(d => Math.round(d.getBoundingClientRect().top))})")
    async def look(t):
        return _j.loads(await renderer.inspect("special.html", {**anime, "ttl": t}, probe, style=Style("", None, "tr", char=ch)))

    await tap("c:42:163134:special:ttl")
    cap = next(c for c in session.calls if type(c).__name__ == "EditMessageCaption")
    assert "automatic" in cap.caption
    for action in ("tgp", "tszp1", "tup1", "tswap"):
        await tap(f"c:42:163134:special:{action}")
        assert session.calls[0].show_alert, f"{action} is refused before a title exists"
    await tap("c:42:163134:special:ttlset")
    assert "ONE message" in session.calls[1].text
    await send("Chitose Is in the Ramune Bottle\n2nd Cour")
    assert "EditMessageMedia" in session.names()
    t = await app.store.get_title(42, 163134)
    assert t["lines"] == ["Chitose Is in the Ramune Bottle", "2nd Cour"]
    assert (t["gap"], t["sizes"], t["shifts"], t["swap"]) == (22, [1.0, 1.0, 1.0], [0, 0, 0], False)
    base = await look(t)
    assert base["cols"] == [2, 1], "line 1 is the right-hand column (the upper line), line 2 sits to its left"
    assert base["sizes"][0] > base["sizes"][1], base
    print("typed title:", base)

    kb = datas(next(c for c in session.calls if type(c).__name__ == "EditMessageMedia").reply_markup)
    await tap("c:42:163134:special:ttl")
    kb = datas(next(c for c in session.calls if type(c).__name__ == "EditMessageCaption").reply_markup)
    for want in ("tszm1", "tszp1", "tup1", "tdn1", "tszm2", "tszp2", "tup2", "tdn2", "tswap", "tgm", "tgp", "ttlauto"):
        assert f"c:42:163134:special:{want}" in kb, want
    assert not any(x.endswith(":tszp3") for x in kb), "only as many line controls as there are lines"

    await tap("c:42:163134:special:tszp1"); await tap("c:42:163134:special:tszp1")       # line 1 -> 120%
    t = await app.store.get_title(42, 163134)
    assert t["sizes"] == [1.2, 1.0, 1.0]
    big = await look(t)
    assert big["sizes"][0] > base["sizes"][0] * 1.15 and big["sizes"][1] == base["sizes"][1], big     # only line 1 changed
    await tap("c:42:163134:special:tszm2")                                                   # line 2 -> 90%
    t = await app.store.get_title(42, 163134)
    assert t["sizes"] == [1.2, 0.9, 1.0]
    small = await look(t)
    assert small["sizes"][0] == big["sizes"][0] and small["sizes"][1] < big["sizes"][1], small       # only line 2 changed
    await tap("c:42:163134:special:tup1"); await tap("c:42:163134:special:tdn2")
    t = await app.store.get_title(42, 163134)
    assert t["shifts"] == [-30, 30, 0]
    moved = await look(t)
    assert moved["ys"][0] == small["ys"][0] - 30 and moved["ys"][1] == small["ys"][1] + 30, (small, moved)   # each line moves on its own
    await tap("c:42:163134:special:tswap")
    assert (await app.store.get_title(42, 163134))["swap"] is True
    assert (await look(await app.store.get_title(42, 163134)))["cols"] == [1, 2], "swap puts line 1 on the left"
    await tap("c:42:163134:special:tswap")
    await tap("c:42:163134:special:tgp")
    assert (await app.store.get_title(42, 163134))["gap"] == 28
    for _ in range(20):
        await app.store.adjust_title(42, 163134, d_gap=6, line=0, d_size=0.1, d_shift=60)
    t = await app.store.get_title(42, 163134)
    assert (t["gap"], t["sizes"][0], t["shifts"][0]) == (90, 2.0, 500), "all controls are clamped"

    # a SINGLE line can now be made bigger or smaller (the old buttons only touched 'small' lines)
    one = {"lines": ["One Piece"], "gap": 22, "sizes": [1.0, 1.0, 1.0], "shifts": [0, 0, 0], "swap": False}
    s100 = (await look(one))["sizes"][0]
    s150 = (await look({**one, "sizes": [1.5, 1.0, 1.0]}))["sizes"][0]
    s60 = (await look({**one, "sizes": [0.6, 1.0, 1.0]}))["sizes"][0]
    assert s150 > s100 * 1.4 and s60 < s100 * 0.7, (s60, s100, s150)
    await app.store.clear_title(42, 163134)
    await app.store.set_title(42, 163134, ["Chitose Is in the Ramune Bottle"])
    await tap("c:42:163134:special:tszp1")
    assert (await app.store.get_title(42, 163134))["sizes"][0] == 1.1

    # typing only one line gets a helpful hint
    await tap("c:42:163134:special:ttlset")
    await send("Just one line")
    assert any("only received one line" in (c.text or "") for c in session.calls if type(c).__name__ == "SendMessage")
    await tap("c:42:163134:special:ttlauto")
    assert await app.store.get_title(42, 163134) is None
    print("title controls OK")

    # 20) Edit text: synopsis, genres, season line, episode label (per anime, every design)
    await tap("c:42:163134:animeposter9:menu")
    kb = datas(next(c for c in session.calls if type(c).__name__ == "EditMessageCaption").reply_markup)
    assert "c:42:163134:animeposter9:edt" in kb, "Edit text button in the Customize menu"
    await tap("c:42:163134:animeposter9:edt")
    cap = next(c for c in session.calls if type(c).__name__ == "EditMessageCaption")
    kb = datas(cap.reply_markup)
    for want in ("edf_syn", "edf_gen", "edf_sea", "edf_epi"):
        assert f"c:42:163134:animeposter9:{want}" in kb, want
    assert not any(x.endswith(":edreset") for x in kb), "no reset button until something is edited"
    await tap("c:42:163134:animeposter9:edf_syn")
    assert "new synopsis" in session.calls[1].text and "AniList says" in session.calls[1].text
    await send("A brand new synopsis for the second part.")
    assert "EditMessageMedia" in session.names()
    await tap("c:42:163134:animeposter9:edf_gen"); await send("Action, Comedy, Fantasy, Drama, Mystery")
    await tap("c:42:163134:animeposter9:edf_sea"); await send("2nd Cour • Fall 2026")
    await tap("c:42:163134:animeposter9:edf_epi"); await send("11 episodes")
    ed = await app.store.get_edits(42, 163134)
    assert ed == {"synopsis": "A brand new synopsis for the second part.", "genres": "Action, Comedy, Fantasy, Drama",
                  "season_line": "2nd Cour • Fall 2026", "episodes_label": "11 episodes"}, ed
    edited = apply_edits(anime, ed)
    assert edited["genres4"] == ["Action", "Comedy", "Fantasy", "Drama"] and len(edited["genres"]) == 3
    seen = {}
    orig_html = renderer.html
    renderer.html = lambda tpl, a, variant="", style=None: (seen.update(a=a), orig_html(tpl, a, variant, style))[1]
    await app.render(163134, app.spec("animeposter9"), 42)
    renderer.html = orig_html
    assert seen["a"]["description"] == "A brand new synopsis for the second part." and seen["a"]["season_line"] == "2nd Cour • Fall 2026"
    h9 = orig_html("poster9.html", edited, "", Style("", None, "tr"))
    assert "2nd Cour • Fall 2026 • 11 episodes" in h9 and "Fantasy" in h9 and "brand new synopsis" in h9
    h3 = orig_html("poster3.html", edited, "", Style("", None, "tr"))
    assert "2nd Cour • Fall 2026" in h3 and ">11<" in h3.replace(" ", ""), "poster 3 bar shows the edited season line and episode count"
    await tap("c:42:163134:animeposter9:edt")
    kb = datas(next(c for c in session.calls if type(c).__name__ == "EditMessageCaption").reply_markup)
    assert any(x.endswith(":edreset") for x in kb)
    await tap("c:42:163134:animeposter9:edf_syn"); await send("x" * 601)
    assert "limit" in session.calls[0].text, "over-long text is refused"
    await send("-")                                              # "-" puts one field back to AniList's text
    assert "synopsis" not in await app.store.get_edits(42, 163134)
    await tap("c:42:163134:animeposter9:edreset")
    assert await app.store.get_edits(42, 163134) == {}
    print("edit text OK")

    # 21) HD export is really 2560x1440 (normal file stays 1280x720), using TMDB's full-size art
    def doc_size(call):
        return Image.open(io.BytesIO(call.document.data)).size
    await app.store.set_art_idx(42, 163134, 0)
    await tap("f:42:163134:animeposter9")
    normal = next(c for c in session.calls if type(c).__name__ == "SendDocument")
    await tap("h:42:163134:animeposter9")
    hd = next(c for c in session.calls if type(c).__name__ == "SendDocument")
    assert doc_size(normal) == (1280, 720) and doc_size(hd) == (2560, 1440), (doc_size(normal), doc_size(hd))
    assert hd.document.filename.endswith("_HD.png") and not normal.document.filename.endswith("_HD.png")
    uri = next(iter(app.cache._hd.values()))
    assert Image.open(io.BytesIO(__import__("base64").b64decode(uri.split(",", 1)[1]))).width == 2560, "3200px original is shrunk to 2560"
    print("HD export OK:", doc_size(normal), "->", doc_size(hd), f"({len(hd.document.data) // 1024} KB)")

    # 22) colours taken from the character
    await tap("c:42:163134:special:col_char")
    assert "EditMessageMedia" in session.names() and (await app.store.get(42)).scheme.count("#") >= 2
    await tap("c:42:999:special:col_char")
    assert session.calls[0].show_alert, "no character for that anime -> refused"
    import base64 as _b64
    from scripts.preview import sample_character
    pal = _sch.from_image(_b64.b64decode(sample_character().split(",")[1]))
    assert pal and len(pal.split(",")) == 3 and len(set(pal.split(","))) == 3, pal
    print("character colours OK:", pal)

    # 23) Preview all: one picture, numbered buttons, tapping a number turns the sheet into that banner
    await tap("pv:42:163134:animeposter9")
    names = session.names()
    assert names.count("SendPhoto") == 1 and "DeleteMessage" in names, names
    sheet = next(c for c in session.calls if type(c).__name__ == "SendPhoto")
    grid_img = Image.open(io.BytesIO(sheet.photo.data))
    nums = [b for row in sheet.reply_markup.inline_keyboard for b in row]
    assert grid_img.width == 3 * 640 + 4 * 18 and len(nums) == 13, (grid_img.size, len(nums))
    assert nums[0].text == "1" and nums[0].callback_data.startswith("t:42:163134:") and "all designs" in sheet.caption.lower() or "ᴀʟʟ ᴅᴇꜱɪɢɴꜱ" in sheet.caption
    print("preview grid:", grid_img.size, f"{len(sheet.photo.data) // 1024} KB,", len(nums), "designs")
    open("/tmp/grid_test.jpg", "wb").write(sheet.photo.data)
    await tap(nums[3].callback_data)
    assert "EditMessageMedia" in session.names(), "tapping a number renders that design into the message"
    from bot.keyboards import grid_caption
    assert "special design is not shown" in grid_caption(app.templates[:3], True).lower() or "ɴᴏᴛ ꜱʜᴏᴡɴ" in grid_caption(app.templates[:3], True)

    # 24) rate limiting protects a public bot
    rl = RateLimiter(5, exempt=frozenset({9}))
    rl.check(1); rl.check(1, 3)
    try:
        rl.check(1, 3); raise AssertionError("should be limited")
    except RateLimited as e:
        assert 0 < e.retry_after <= 60
    for _ in range(50):
        rl.check(9)                                              # admins are exempt
    rl.check(2)                                                  # other people are unaffected
    app.limiter = RateLimiter(1)
    await app.render(163134, app.spec("animeposter4"), 77)
    try:
        await app.render(163134, app.spec("animeposter4"), 77); raise AssertionError("should be limited")
    except RateLimited:
        pass
    app.limiter = RateLimiter(1)
    await tap("t:42:163134:animeposter2"); await tap("t:42:163134:animeposter3")
    assert any("Slow down" in (c.text or "") for c in session.calls if type(c).__name__ == "SendMessage"), "the user is told to slow down"
    app.limiter = RateLimiter(0)
    print("rate limit OK")

    # 25) optional allow-list
    mw = AllowListMiddleware(frozenset({1}), frozenset({9}))
    reached = []
    async def handler(event, data):
        reached.append(event.from_user.id)
    for uid_ in (1, 9, 2):
        m = Message(message_id=1, date=datetime.now(), chat=chat, from_user=User(id=uid_, is_bot=False, first_name="u"), text="hi").as_(bot)
        session.calls.clear()
        await mw(handler, m, {})
    assert reached == [1, 9], reached
    assert "private" in session.calls[0].text
    await AllowListMiddleware(frozenset(), frozenset())(handler, m, {})      # empty list = open to everyone
    assert reached == [1, 9, 2]
    print("allow-list OK")

    await renderer.close()
    await http.aclose()
    print("ALL OK")


asyncio.run(main())
