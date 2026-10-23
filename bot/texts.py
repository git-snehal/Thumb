"""Message copy and text styling."""
from __future__ import annotations

import html
import random

_SC = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ")
FANCY = True
TMDB_ON = False      # set at startup when a TMDB key is configured (TMDB requires attribution)


def sc(text: str) -> str:
    """Small-caps styling (falls back to plain text when FANCY_TEXT is off)."""
    return text.lower().translate(_SC) if FANCY else text


esc = html.escape

# Short, well-known lines. Edit freely.
QUOTES = [
    ("If you don't take risks, you can't create a future.", "Monkey D. Luffy"),
    ("A lesson without pain is meaningless.", "Edward Elric"),
    ("People's lives don't end when they die. It ends when they lose faith.", "Itachi Uchiha"),
    ("The world isn't perfect. But it's there for us, doing the best it can.", "Roy Mustang"),
    ("Fear is not evil. It tells you what your weakness is.", "Gildarts Clive"),
]


def start_frames() -> list[str]:
    bar = lambda n: "▰" * n + "▱" * (10 - n)
    return [
        f"⚡ <b>{sc('starting now')}</b>\n\n<code>{bar(1)}</code>",
        f"⚡ <b>{sc('starting now')}</b> .\n\n<code>{bar(4)}</code>",
        f"⚡ <b>{sc('starting now')}</b> ..\n\n<code>{bar(7)}</code>",
        f"✨ <b>{sc('almost ready')}</b> ...\n\n<code>{bar(10)}</code>",
    ]


def start_text(name: str) -> str:
    q, who = random.choice(QUOTES)
    hello = sc("hello")
    tagline = sc("i'm an anime thumbnail maker bot, built with love.")
    help_word, use, rest = sc("help"), sc("use"), sc("for the full guide and command list.")
    return (
        f"🌸 <b>{hello} {esc(name)}</b>,\n\n"
        f"<blockquote>≡ 🎨 {tagline}</blockquote>\n"
        f"<blockquote>❝ {esc(q)} ❞\n— {sc(who)}</blockquote>\n"
        f"<blockquote>» <b>{help_word} :</b> {use} /help {rest}</blockquote>"
    )


def help_text() -> str:
    fallback = ("If AniList is down or doesn't have a title, I search TMDB instead. You can also paste a themoviedb.org "
                "link or <code>tmdb:tv/1399</code>.\n") if TMDB_ON else ""
    tmdb_art = ", or flip through HD art from TMDB" if TMDB_ON else ""
    credit = "\n\n<i>This product uses the TMDB API but is not endorsed or certified by TMDB.</i>" if TMDB_ON else ""
    blocks = [
        f"📖 <b>{sc('guide')}</b>\n",
        f"<blockquote>🖼 <b>{sc('make a thumbnail')}</b>\n"
        "/poster &lt;name&gt;\n"
        "/poster id:163134\n"
        "/poster https://anilist.co/anime/163134\n"
        "…or reply to a message containing a title with /poster\n"
        f"{fallback}</blockquote>",
        f"<blockquote>🎛 <b>{sc('switch templates')}</b>\n"
        "Tap the buttons under the banner. The same message updates in place.</blockquote>",
        f"<blockquote>✨ <b>{sc('special design')}</b>\n"
        "Tap “Special Design” under a banner, send a character image (transparent PNG is best, "
        "normal images get their background removed), then change the background colors "
        "or nudge the character.</blockquote>",
        f"<blockquote>🛠 <b>{sc('under every banner')}</b>\n"
        "👀 Preview all: every design in one picture, tap a number to use it\n"
        "✨ HD file: a sharper 2560×1440 PNG\n"
        "Customize → Edit text: fix the synopsis, genres, season line or episode label</blockquote>",
        f"<blockquote>🌄 <b>{sc('background art')}</b>\n"
        f"Customize → Background image: upload your own picture (a wide 16:9 file looks best){tmdb_art}. "
        "Works on Template 1 and Posters 2 to 10.</blockquote>",
        f"<blockquote>🎨 <b>{sc('make it yours')}</b>\n"
        "/settings — brand text, logo (PNG), corner position and font.\n"
        "Or tap “Customize” under any banner and watch it update live.</blockquote>",
        f"<blockquote>🧰 <b>{sc('other')}</b>\n"
        "/emojiid — send me Premium emoji and I'll reply with their IDs\n"
        "/version — which version of the bot is running\n"
        "/cancel — cancel a pending text/logo upload</blockquote>",
    ]
    return "\n".join(blocks) + credit
