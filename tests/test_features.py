"""Tests for fanart.tv characters/logos, extra art, upscaling, badges, title language, watermark and the private-chat
lookup. No network, no Telegram and no Chromium needed:   python -m pytest tests/test_features.py   (or run it directly)."""
from __future__ import annotations

import asyncio
import io
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
from PIL import Image

from bot import artsources, fanart, watermark
from bot.anilist import AniList
from bot.app import App, apply_edits, with_title_lang
from bot.assets import upscale_small
from bot.handlers import _plain_private_text
from bot.keyboards import BADGE_PRESETS, badge_list, edit_kb, next_title_lang, panel_kb
from bot.registry import DEFAULT_TEMPLATES
from bot.render import Renderer
from bot.store import Store
from bot.style import Style
from bot.tmdb import rank_logos

ROOT = Path(__file__).resolve().parent.parent

MEDIA = {
    "id": 163134, "idMal": 54321, "siteUrl": "x",
    "title": {"romaji": "Alya-san", "english": "Alya Sometimes Hides Her Feelings in Russian", "native": "ロシア語"},
    "description": "Alya is a transfer student.", "format": "TV", "status": "FINISHED", "season": "SUMMER",
    "seasonYear": 2024, "episodes": 12, "duration": 24, "averageScore": 79,
    "genres": ["Comedy", "Romance", "Slice of Life", "Drama"], "bannerImage": None,
    "coverImage": {"extraLarge": "https://img.test/c.png", "large": "https://img.test/c.png", "color": "#e4a1a1"},
    "studios": {"nodes": [{"name": "Doga Kobo"}]}, "characters": {"edges": []}, "streamingEpisodes": [],
}


def run(coro):
    return asyncio.run(coro)


def png(w, h, color=(200, 50, 50), alpha_fn=None) -> bytes:
    img = Image.new("RGBA", (w, h), (*color, 255))
    if alpha_fn:
        a = Image.new("L", (w, h), 255)
        alpha_fn(a)
        img.putalpha(a)
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def cutout(a: Image.Image) -> None:           # transparent border around an opaque middle
    w, h = a.size
    a.paste(0, (0, 0, w, h // 4))
    a.paste(0, (0, 0, w // 4, h))


# ----------------------------------------------------------------------------- fanart.tv helpers
def test_pick_urls_language_then_likes():
    rec = {"hdtvlogo": [{"url": "ja1", "lang": "ja", "likes": "50"}, {"url": "en_low", "lang": "en", "likes": "1"},
                        {"url": "en_hi", "lang": "en", "likes": "9"}],
           "clearlogo": [{"url": "en_hi", "lang": "en", "likes": "9"}, {"url": "", "lang": "en"}]}
    assert fanart.pick_urls(rec, fanart.SHOW_LOGOS) == ["en_hi", "en_low", "ja1"]


def test_prepare_character_rules():
    assert fanart.prepare_character(png(600, 800)) is None                       # opaque image: not a cut-out
    assert fanart.prepare_character(b"not an image") is None
    out = fanart.prepare_character(png(300, 500, alpha_fn=cutout))
    img = Image.open(io.BytesIO(out))
    assert img.mode == "RGBA"
    # the transparent top quarter and left quarter are cropped (225x375 left), then enlarged by the 2x cap
    assert img.size == (450, 750)
    huge = Image.open(io.BytesIO(fanart.prepare_character(png(2400, 3600, alpha_fn=cutout))))
    assert huge.height == 2000


def test_prepare_logo_crops_and_limits():
    def corner(a):
        a.paste(0, (0, 0, a.width, a.height))
        a.paste(255, (300, 100, 700, 180))
    out = Image.open(io.BytesIO(fanart.prepare_logo(png(1000, 300, alpha_fn=corner))))
    assert out.size == (400, 80)
    assert fanart.prepare_logo(png(1000, 300, alpha_fn=lambda a: a.paste(0, (0, 0, a.width, a.height)))) is None


def test_rank_logos():
    items = [{"file_path": "/ja.png", "iso_639_1": "ja", "width": 800, "vote_average": 9},
             {"file_path": "/fr.png", "iso_639_1": "fr", "width": 800},
             {"file_path": "/x.svg", "iso_639_1": "en", "width": 800},
             {"file_path": "/small.png", "iso_639_1": "en", "width": 100},
             {"file_path": "/en2.png", "iso_639_1": "en", "width": 500, "vote_average": 5},
             {"file_path": "/en1.png", "iso_639_1": "en", "width": 700, "vote_average": 6},
             {"file_path": "/none.png", "iso_639_1": None, "width": 900}]
    assert rank_logos(items) == ["/en1.png", "/en2.png", "/none.png", "/ja.png"]


def _fanart_world(tmp: Path, calls: list):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if req.url.host == "raw.githubusercontent.com":
            return httpx.Response(200, json=[{"anilist_id": 163134, "tvdb_id": 4242}, {"anilist_id": 1}])
        if req.url.host == "webservice.fanart.tv":
            assert req.url.params["api_key"] == "KEY"
            if req.url.path == "/v3/tv/4242":
                return httpx.Response(200, json={"characterart": [{"url": "https://assets.fanart.tv/a.png", "likes": "3"}],
                                                 "hdtvlogo": [{"url": "https://assets.fanart.tv/l.png", "lang": "en"}]})
            return httpx.Response(404)
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_fanart_client_maps_anilist_to_tvdb_and_reads_record():
    async def go():
        with tempfile.TemporaryDirectory() as d:
            calls: list[str] = []
            async with _fanart_world(Path(d), calls) as http:
                f = fanart.Fanart(http, "KEY", None, Path(d))
                anime = {"id": 163134, "title": "Alya"}
                assert await f.character_urls(anime) == ["https://assets.fanart.tv/a.png"]
                assert await f.logo_urls(anime) == ["https://assets.fanart.tv/l.png"]
                n_before = len(calls)
                await f.character_urls(anime)                       # second time: served from memory
                assert len(calls) == n_before
                assert (Path(d) / "anilist_tvdb.json").is_file()   # the mapping is kept on disk for a week
                # a title that fanart.tv doesn't know gives empty lists, not an error
                assert await f.character_urls({"id": 1, "title": "x"}) == []
            off = fanart.Fanart(httpx.AsyncClient(), "", None, Path(d))
            assert not off.enabled and await off.character_urls({"id": 1}) == []
    run(go())


def test_fanart_failures_are_not_remembered_and_diagnose_explains():
    async def go():
        with tempfile.TemporaryDirectory() as d:
            status = {"code": 500}
            hits = []

            def handler(req):
                if req.url.host == "raw.githubusercontent.com":
                    return httpx.Response(200, json=[{"anilist_id": 5, "tvdb_id": 99}])
                hits.append(status["code"])
                if status["code"] == 200:
                    return httpx.Response(200, json={"characterart": [{"url": "https://assets.fanart.tv/x.png"}]})
                return httpx.Response(status["code"], json={})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                f = fanart.Fanart(http, "KEY", None, Path(d))
                anime = {"id": 5, "title": "T"}
                assert await f.character_urls(anime) == []                       # a server hiccup...
                status["code"] = 200
                assert await f.character_urls(anime) == ["https://assets.fanart.tv/x.png"]   # ...is retried, not cached
                status["code"] = 401
                text = " ".join(await f.diagnose(anime))
                assert "rejected the API key" in text and "ID used: 99" in text
                status["code"] = 404
                assert "no art for this show" in " ".join(await f.diagnose(anime))
                n = len(hits)
                await f.character_urls(anime)                                    # a 404 IS remembered for a while
                assert len(hits) == n
                missing = await f.diagnose({"id": 77, "title": "Unknown"})       # not in the id map, no TMDB
                assert "no TheTVDB/TMDB id" in " ".join(missing)
            off = fanart.Fanart(httpx.AsyncClient(), "", None, Path(d))
            assert "MISSING" in (await off.diagnose({"id": 1}))[0]
    run(go())


# ----------------------------------------------------------------------------- extra art + upscaling
def test_extra_art_parsers():
    jikan = {"data": [{"jpg": {"image_url": "s1", "large_image_url": "L1"}}, {"jpg": {"image_url": "s2"}}, {"jpg": {}}]}
    assert artsources.jikan_urls(jikan) == ["L1", "s2"]
    kitsu = {"included": [{"attributes": {"posterImage": {"original": "K1", "large": "k1"}}}, {"attributes": {}}]}
    assert artsources.kitsu_urls(kitsu) == ["K1"]
    assert artsources.source_name("https://cdn.myanimelist.net/x.jpg") == "MyAnimeList"
    assert artsources.source_name("https://media.kitsu.app/x.jpg") == "Kitsu"
    assert artsources.source_name("/abc.jpg") == "TMDB"


def test_extra_posters_skip_tmdb_titles_and_survive_failures():
    async def go():
        def handler(req):
            if "jikan" in req.url.host:
                return httpx.Response(200, json={"data": [{"jpg": {"large_image_url": "J1"}}]})
            return httpx.Response(500)                               # Kitsu is down: Jikan's pictures still come through
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            assert await artsources.extra_posters(http, {"id": 5, "mal_id": 9}) == ["J1"]
            assert await artsources.extra_posters(http, {"id": -4, "source": "tmdb", "mal_id": 9}) == []
    run(go())


def test_upscale_small_only_enlarges_small_pictures():
    small = io.BytesIO()
    Image.new("RGB", (460, 650), (90, 120, 200)).save(small, "JPEG")
    out, mime = upscale_small(small.getvalue())
    img = Image.open(io.BytesIO(out))
    assert mime == "image/jpeg" and 1300 <= img.height <= 1400
    big = io.BytesIO()
    Image.new("RGB", (1000, 1500)).save(big, "JPEG")
    assert upscale_small(big.getvalue()) is None
    assert upscale_small(b"junk") is None


# ----------------------------------------------------------------------------- title language, badges, settings
def _anime():
    class Http:
        async def post(self, *a, **k):
            return SimpleNamespace(status_code=200, headers={}, json=lambda: {"data": {"Media": MEDIA}})
    return run(AniList(Http()).media(163134))


def test_title_language_switch():
    a = _anime()
    assert a["mal_id"] == 54321
    assert with_title_lang(a, None) is a and with_title_lang(a, "auto") is a
    romaji = with_title_lang(a, "romaji")
    assert romaji["title"] == "Alya-san" and romaji["title_a"] and "title_big" in romaji
    assert with_title_lang(a, "native")["title"] == "ロシア語"
    tmdb_like = {**a, "title_native": None}
    assert with_title_lang(tmdb_like, "native") is tmdb_like             # a title without that language keeps the default
    assert [next_title_lang(x) for x in (None, "english", "romaji", "native", "auto")] == ["english", "romaji", "native", "auto", "english"]


def test_badges_apply_and_toggle_helpers():
    a = _anime()
    assert "badges" not in apply_edits(a, {})
    out = apply_edits(a, {"badges": "SUB, 1080p,, EP 12, Completed, Extra"})
    assert out["badges"] == ["SUB", "1080p", "EP 12", "Completed"]          # at most four
    assert badge_list({"badges": "SUB, DUB"}) == ["SUB", "DUB"]
    kb = edit_kb(1, 2, "template1", {"badges": "SUB"})
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert any("✅" in t for t in labels)
    assert sum(len(r) for r in kb.inline_keyboard) >= len(BADGE_PRESETS)
    for row in kb.inline_keyboard:
        for b in row:
            assert len(b.callback_data.encode()) <= 64


def test_panel_shows_title_language_and_logo_state():
    kb = panel_kb(1, 2, "template1", False, "romaji", "off")
    labels = " ".join(b.text for row in kb.inline_keyboard for b in row)
    assert "ʀᴏᴍᴀᴊɪ" in labels.lower() or "romaji" in labels.lower()
    assert "off" in labels.lower() or "ᴏꜰꜰ" in labels


def test_store_upgrades_old_databases_and_keeps_new_settings():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "bot.db"
        con = sqlite3.connect(db)                                           # a database made by version 2.1.0
        con.execute("CREATE TABLE user_settings (user_id INTEGER PRIMARY KEY, brand_text TEXT, brand_off INTEGER DEFAULT 0, "
                    "logo_path TEXT, position TEXT, font TEXT, scheme TEXT, logo_position TEXT)")
        con.execute("CREATE TABLE text_edits (user_id INTEGER, anime_id INTEGER, synopsis TEXT, genres TEXT, season_line TEXT, "
                    "episodes_label TEXT, ts REAL, PRIMARY KEY (user_id, anime_id))")
        con.execute("CREATE TABLE characters (user_id INTEGER, anime_id INTEGER, path TEXT, dx INTEGER DEFAULT 0, "
                    "scale REAL DEFAULT 1.0, ts REAL, PRIMARY KEY (user_id, anime_id))")
        con.execute("INSERT INTO user_settings (user_id, brand_text) VALUES (7, 'Old brand')")
        con.commit(); con.close()

        async def go():
            st = Store(db, Path(d) / "logos")
            s = await st.get(7)
            assert s.brand_text == "Old brand" and s.title_lang is None and s.title_logo is None
            await st.update(7, title_lang="romaji", title_logo="off")
            s = await st.get(7)
            assert (s.title_lang, s.title_logo) == ("romaji", "off")
            await st.set_edit(7, 1, "badges", "SUB, 4K")
            assert (await st.get_edits(7, 1)) == {"badges": "SUB, 4K"}
            await st.set_edit(7, 1, "badges", None)
            assert await st.get_edits(7, 1) == {}                           # an empty row is cleaned up
            await st.save_character(7, 1, png(10, 10), src_idx=3)
            assert (await st.get_character(7, 1))["src_idx"] == 3
            await st.save_character(7, 1, png(10, 10))                      # an upload replaces it: no fanart index
            assert (await st.get_character(7, 1))["src_idx"] is None
        run(go())


# ----------------------------------------------------------------------------- picking a fanart.tv character
class _FakeStore:
    def __init__(self): self.saved = []
    async def save_character(self, uid, mid, png_bytes, src_idx=None): self.saved.append((uid, mid, src_idx))


def _fake_app(urls, files):
    class Cache:
        fanart = SimpleNamespace(enabled=True, fetch=None)
        async def get(self, mid): return {"id": mid}
    cache = Cache()
    async def fetch(url): return files.get(url)
    cache.fanart.fetch = fetch
    self = SimpleNamespace(cache=cache, store=_FakeStore())
    async def urls_for(anime): return urls
    self.character_candidates = urls_for
    return self


def test_pick_character_skips_unusable_candidates_and_wraps():
    good = png(300, 500, alpha_fn=cutout)
    files = {"u0": png(300, 500), "u1": b"broken", "u2": good, "u3": None}
    app = _fake_app(["u0", "u1", "u2", "u3"], files)
    assert run(App.pick_character(app, 5, 9, 0)) == 2                      # u0 is opaque, u1 broken: u2 is the first usable
    assert app.store.saved == [(5, 9, 2)]
    app.store.saved.clear()
    assert run(App.pick_character(app, 5, 9, 3)) == 2                      # starting at u3 wraps round to u2
    assert run(App.pick_character(_fake_app([], {}), 5, 9)) is None        # no key / nothing found


# ----------------------------------------------------------------------------- private-chat lookup filter
def _msg(text, chat="private", entities=None):
    return SimpleNamespace(chat=SimpleNamespace(type=chat), text=text, entities=entities)


def test_private_text_filter():
    assert _plain_private_text(_msg("Solo Leveling"))
    assert not _plain_private_text(_msg("/poster x"))                       # commands keep their own handlers
    assert not _plain_private_text(_msg("Solo Leveling", chat="supergroup"))  # groups need /poster
    assert not _plain_private_text(_msg("Solo Leveling", chat="group"))
    assert not _plain_private_text(_msg(None))                              # photos, stickers...
    assert not _plain_private_text(_msg("hi", entities=[SimpleNamespace(type="custom_emoji")]))   # the emoji-ID helper's job


# ----------------------------------------------------------------------------- watermark
def test_invisible_watermark_survives_jpeg_and_is_keyed():
    h, w = 360, 640
    y, x = np.mgrid[0:h, 0:w]
    base = Image.fromarray(np.stack([x / w * 255, y / h * 255, (x + y) / (w + h) * 255], -1).astype(np.uint8))
    src = io.BytesIO(); base.save(src, "JPEG", quality=90)
    marked = watermark.apply(src.getvalue(), "jpeg", key="k1")
    again = io.BytesIO(); Image.open(io.BytesIO(marked)).save(again, "JPEG", quality=75)    # forwarded through Telegram
    img = Image.open(io.BytesIO(again.getvalue()))
    assert watermark.detect(img, "k1") > watermark.THRESHOLD * 5
    assert abs(watermark.detect(img, "other")) < watermark.THRESHOLD
    assert abs(watermark.detect(Image.open(io.BytesIO(src.getvalue())), "k1")) < watermark.THRESHOLD
    assert watermark.apply(src.getvalue(), "jpeg") == src.getvalue()        # nothing configured: bytes untouched
    visible = watermark.apply(src.getvalue(), "png", text="MYBOT")
    assert Image.open(io.BytesIO(visible)).size == (w, h) and visible != src.getvalue()


# ----------------------------------------------------------------------------- templates (HTML only, no browser)
def _renderer():
    return Renderer(ROOT / "templates", ROOT / "assets", 1)


def _html(file, anime, **kw):
    return _renderer().html(file, anime, kw.pop("variant", ""), Style(**kw))


def _sample(**extra):
    a = _anime()
    return {**a, "cover": "data:image/png;base64,AAAA", "art": "data:image/png;base64,AAAA", "art_wide": True, **extra}


def test_every_plain_template_renders_with_and_without_extras():
    plain = [t for t in DEFAULT_TEMPLATES if not t.special]
    for t in plain:
        _html(t.file, _sample(), variant=t.variant)                                     # nothing extra: still fine
        _html(t.file, _sample(badges=["SUB", "1080p"], title_logo="data:image/png;base64,BBBB"), variant=t.variant)


def test_badges_show_on_the_designs_that_support_them():
    for f in ("template1.html", "poster2.html", "poster5.html", "poster7.html", "poster8.html", "poster9.html", "poster10.html",
              "poster11.html", "poster12.html", "poster13.html"):
        marker = "ribbon" if f == "poster13.html" else "uchips"          # Poster 13 shows badges as its ribbon
        assert "1080p" in _html(f, _sample(badges=["SUB", "1080p"])), f
        assert "1080p" not in _html(f, _sample()), f
        if marker == "uchips":
            assert "uchips" in _html(f, _sample(badges=["SUB"])) and "uchips" not in _html(f, _sample()), f


def test_title_logo_replaces_text_title_with_fallback():
    for f in ("poster9.html", "poster10.html", "poster11.html", "poster12.html"):
        with_logo = _html(f, _sample(title_logo="data:image/png;base64,BBBB"))
        assert 'class="tlogo"' in with_logo and 'id="t"' not in with_logo
        without = _html(f, _sample(title_logo=None))
        assert 'id="t"' in without and 'class="tlogo"' not in without


def test_poster13_splits_the_title_and_handles_logo_and_ribbon():
    plain = _html("poster13.html", _sample())
    assert 'id="b"' in plain and 'class="tlogo"' not in plain
    assert "12 episodes" in plain                                               # no badges: the ribbon shows the episode label
    badged = _html("poster13.html", _sample(badges=["SUB", "4K"]))
    assert "SUB" in badged and "4K" in badged and "12 episodes" not in badged
    logo = _html("poster13.html", _sample(title_logo="data:image/png;base64,BBBB"))
    assert 'class="tlogo"' in logo and 'id="b"' not in logo
    one_word = _html("poster13.html", {**_sample(), "title": "Bleach", "title_small": "", "title_big": "Bleach"})
    assert 'id="s"' not in one_word and "Bleach" in one_word


def test_new_posters_survive_missing_data():
    bare = _sample(score10=None, star_pct=None, studio=None, genres=[], genres4=[], episodes=None, year=None)
    for f in ("poster11.html", "poster12.html", "poster13.html"):
        _html(f, bare)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok  ", name)
    print("all feature tests passed")
