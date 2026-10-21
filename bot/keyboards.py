from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import fonts, icons, schemes
from .anilist import SearchHit
from .registry import TemplateSpec
from .store import UserSettings
from .style import POSITIONS
from .texts import esc, sc


def btn(label: str, data: str, slot: str | None = None, emoji: str = "", style: str | None = None) -> InlineKeyboardButton:
    """One button. Uses the animated custom emoji for `slot` if configured, else a plain emoji."""
    icon = icons.get(slot)
    text = sc(label)
    if emoji and not icon:
        text = f"{emoji} {text}"
    return InlineKeyboardButton(text=text, callback_data=data, style=style, icon_custom_emoji_id=icon)


# ---- anime search picker --------------------------------------------------
def picker_kb(uid: int, hits: list[SearchHit]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=h.label, callback_data=f"p:{uid}:{h.id}")] for h in hits
    ])


# ---- banner ---------------------------------------------------------------
def template_kb(uid: int, media_id: int, templates: list[TemplateSpec], current: str) -> InlineKeyboardMarkup:
    """First template gets its own full-width row, the rest sit two per row."""
    def one(t: TemplateSpec) -> InlineKeyboardButton:
        on = t.key == current
        return btn(t.label, f"t:{uid}:{media_id}:{t.key}", "active" if on else "template",
                   emoji="✅" if on else "🎞", style="success" if on else "primary")

    normal = [t for t in templates if not t.special]
    special = [t for t in templates if t.special]
    rows: list[list[InlineKeyboardButton]] = []
    if normal:
        rows.append([one(normal[0])])
        rest = [one(t) for t in normal[1:]]
        rows += [rest[i:i + 2] for i in range(0, len(rest), 2)]
    for t in special:                      # the Special Design gets its own full-width button
        on = t.key == current
        rows.append([btn(t.label.replace("✨ ", ""), f"t:{uid}:{media_id}:{t.key}", "active" if on else "special",
                         "✅" if on else "✨", "success" if on else "primary")])
    if current in {t.key for t in special}:   # controls that only make sense for the special design
        rows.append([
            btn("Colors", f"c:{uid}:{media_id}:{current}:colors", "colors", "🎨"),
            btn("Character", f"c:{uid}:{media_id}:{current}:char", "character", "🧍"),
            btn("Title", f"c:{uid}:{media_id}:{current}:ttl", "title", "✏️"),
        ])
    rows.append([
        btn("Customize", f"c:{uid}:{media_id}:{current}:menu", "customize", "🎨"),
        btn("Preview all", f"pv:{uid}:{media_id}:{current}", "preview", "👀"),
    ])
    rows.append([
        btn("Get file", f"f:{uid}:{media_id}:{current}", "file", "⬇️"),
        btn("HD file", f"h:{uid}:{media_id}:{current}", "hd", "✨"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def grid_caption(shown: list, missing_special: bool) -> str:
    names = " · ".join(f"<b>{i}</b> {esc(t.label.replace('✨ ', ''))}" for i, t in enumerate(shown, 1))
    note = (f"\n<i>{sc('the special design is not shown: add a character for this anime first.')}</i>" if missing_special else "")
    return f"<b>👀 {sc('all designs')}</b>\n<blockquote>{names}</blockquote>\n<i>{sc('tap a number to use that design.')}</i>{note}"


def grid_kb(uid: int, media_id: int, shown: list) -> InlineKeyboardMarkup:
    """Numbered buttons under the contact sheet. They reuse the normal template callbacks, so tapping one turns the
    sheet itself into that banner (with all its usual buttons)."""
    buttons = [InlineKeyboardButton(text=str(i), callback_data=f"t:{uid}:{media_id}:{t.key}", style="primary")
               for i, t in enumerate(shown, 1)]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[i:i + 5] for i in range(0, len(buttons), 5)])


def current_key(message) -> str:
    """The active template, read back from the 'Get file' button (its callback always carries it)."""
    markup = getattr(message, "reply_markup", None)
    for row in (markup.inline_keyboard if markup else []):
        for b in row:
            if b.callback_data and b.callback_data.startswith("f:"):
                return b.callback_data.split(":")[3]
    return ""


def caption(title: str, current: str) -> str:
    return (
        f"<b>{esc(title)}</b>\n\n"
        f"<b>⧉ {sc('select template — anime')}</b>\n\n"
        f"• <b>{sc('current template')}:</b> <code>{current}</code>\n\n"
        f"<blockquote>✅ {sc('selected · tap another to switch · customize for brand and font')}</blockquote>"
    )


# ---- customise panel ------------------------------------------------------
def _cb(uid: int, mid: int, key: str, action: str) -> str:
    return f"c:{uid}:{mid}:{key}:{action}"


def panel_text(s: UserSettings, default_brand: str, default_pos: str, default_logo_pos: str = "tl") -> str:
    if s.brand_off:
        brand = "— removed —"
    else:
        txt = s.brand_text if s.brand_text is not None else (default_brand or "")
        brand = esc(txt) if txt else "none"
    logo = "✅ uploaded" if s.logo_path else "none"
    tpos = POSITIONS.get(s.position or default_pos, "Top right")
    lpos = POSITIONS.get(s.logo_position or default_logo_pos, "Top left")
    font = fonts.get(s.font).label
    return (
        f"<b>🎨 {sc('customize — brand & font')}</b>\n\n"
        f"<blockquote>• <b>{sc('brand text')}:</b> <code>{brand}</code>\n"
        f"• <b>{sc('logo')}:</b> {logo}\n"
        f"• <b>{sc('text position')}:</b> {tpos}\n"
        f"• <b>{sc('logo position')}:</b> {lpos}\n"
        f"• <b>{sc('font')}:</b> {esc(font)}</blockquote>\n"
        f"<i>{sc('text and logo can sit in different corners. changes apply instantly.')}</i>"
    )


def pos_text(kind: str, current: str) -> str:
    what = "brand text" if kind == "text" else "logo"
    return (
        f"<b>📍 {sc('where should the ' + what + ' go?')}</b>\n\n"
        f"<blockquote>• <b>{sc('now')}:</b> {POSITIONS.get(current, current)}</blockquote>\n"
        f"<i>{sc('tap a corner to move it and see the banner update.')}</i>"
    )


def panel_kb(uid: int, mid: int, key: str, standalone: bool) -> InlineKeyboardMarkup:
    c = lambda a: _cb(uid, mid, key, a)
    last = btn("Close", c("close"), "close", "✖️") if standalone else btn("Back", c("back"), "back", "↩️")
    rows = [
        [btn("Brand text", c("txt"), "text", "✏️"), btn("Brand logo", c("logo"), "logo", "🖼")],
        [btn("Text position", c("pos"), "position", "📍"), btn("Logo position", c("lpos"), "position", "📍")],
        [btn("Font", c("font"), "font", "🔤"), btn("Remove brand", c("off"), "remove", "🗑", "danger")],
    ]
    if not standalone:                            # normal posters: main art. Special design: the Next-card pictures
        rows.append([btn("Next-card images" if key == "special" else "Background image", c("bg"), "background", "🌄"),
                     btn("Edit text", c("edt"), "edit", "📝")])
    rows.append([last])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bg_text(label: str, has_custom: bool, n_tmdb: int, special: bool = False) -> str:
    if special:
        title, tip = "next-card images", ("tap Next images for other HD scenes, or AniList to use AniList pictures instead."
                                          if n_tmdb else "these come from AniList (add a TMDB key for HD scenes).")
    else:
        title = "background image"
        tip = ("send a new image to replace it, or remove it to go back to the automatic art." if has_custom else
               "tap Next image to flip through HD art, AniList to use AniList's own picture, or upload your own."
               if n_tmdb else "tap AniList to switch between its cover and banner, or upload your own image (wide 16:9 looks best).")
    return (
        f"<b>🌄 {sc(title)}</b>\n\n"
        f"<blockquote>• <b>{sc('using')}:</b> {esc(label)}</blockquote>\n"
        f"<i>{sc(tip)}</i>"
    )


def bg_kb(uid: int, mid: int, key: str, has_custom: bool, n_tmdb: int, idx: int = 0, special: bool = False) -> InlineKeyboardMarkup:
    c = lambda a: _cb(uid, mid, key, a)
    on_anilist = idx < 0 or not n_tmdb
    rows: list[list[InlineKeyboardButton]] = []
    if not special:
        rows.append([btn("Replace my image" if has_custom else "Upload my image", c("bgup"), "background", "🖼")])
    if has_custom and not special:
        rows.append([btn("Remove my image", c("bgdel"), "remove", "🗑", "danger")])
    else:
        row = []
        if n_tmdb:
            row.append(btn("Next images" if special else "Next image", c("bgnext"), None, "🔄", None if on_anilist else "success"))
        row.append(btn("AniList", c("bganilist"), None, "🅰️", "success" if on_anilist else None))
        rows.append(row)
    rows.append([btn("Back", c("menu"), "back", "↩️")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def position_kb(uid: int, mid: int, key: str, current: str, kind: str = "text") -> InlineKeyboardMarkup:
    c = lambda a: _cb(uid, mid, key, a)
    arrows = {"tl": "↖️", "tr": "↗️", "bl": "↙️", "br": "↘️"}
    prefix = "sp" if kind == "text" else "sl"       # sp<corner> = brand text, sl<corner> = logo

    def one(p: str) -> InlineKeyboardButton:
        on = p == current
        return btn(POSITIONS[p], c(f"{prefix}{p}"), None, "✅" if on else arrows[p], "success" if on else "primary")

    return InlineKeyboardMarkup(inline_keyboard=[
        [one("tl"), one("tr")], [one("bl"), one("br")],
        [btn("Back", c("menu"), "back", "↩️")],
    ])


def font_kb(uid: int, mid: int, key: str, current: str) -> InlineKeyboardMarkup:
    c = lambda a: _cb(uid, mid, key, a)
    items = []
    for f in fonts.FONTS.values():
        on = f.key == current
        # font names are shown as-is (not small-caps) so people recognise them
        items.append(InlineKeyboardButton(
            text=("✅ " if on else "") + f.label, callback_data=c(f"sf{f.key}"),
            style="success" if on else "primary"))
    rows = [items[i:i + 2] for i in range(0, len(items), 2)]
    rows.append([btn("Back", c("menu"), "back", "↩️")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---- start message --------------------------------------------------------
def start_kb(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("Make a thumbnail", "go", "make", "🎬", "primary")],
        [btn("Help", "help", "help", "📖"), btn("Settings", f"c:{uid}:0:-:menu", "settings", "⚙️")],
    ])


# ---- special design: colours + character --------------------------------
def colors_text(label: str) -> str:
    return (
        f"<b>🎨 {sc('special design — colors')}</b>\n\n"
        f"<blockquote>• <b>{sc('background')}:</b> {esc(label)}</blockquote>\n"
        f"<i>{sc('tap a scheme to preview it instantly, or send your own: 1 to 4 hex colors, top to bottom.')}</i>"
    )


def colors_kb(uid: int, mid: int, key: str, current: str) -> InlineKeyboardMarkup:
    c = lambda a: _cb(uid, mid, key, a)

    def one(k: str, dot: str, label: str) -> InlineKeyboardButton:
        on = k == current
        return btn(label, c(f"col_{k}"), None, "✅" if on else dot, "success" if on else "primary")

    items = [one(k, v[1], v[0]) for k, v in schemes.PRESETS.items()] + [one(schemes.AUTO, "🪄", "Auto (cover)")]
    rows = [items[i:i + 2] for i in range(0, len(items), 2)]
    is_custom = current.startswith("#")
    rows.append([btn("From character", c("col_char"), None, "🪄")])
    rows.append([btn("Custom hex colors", c("colhex"), None, "✅" if is_custom else "🎨", "success" if is_custom else None)])
    rows.append([btn("Back", c("back"), "back", "↩️")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def char_text(ch: dict | None) -> str:
    size = f"{round((ch or {}).get('scale', 1.0) * 100)}%"
    shift = (ch or {}).get("dx", 0)
    where = "centered" if shift == 0 else (f"{abs(shift)}px right" if shift > 0 else f"{abs(shift)}px left")
    return (
        f"<b>🧍 {sc('special design — character')}</b>\n\n"
        f"<blockquote>• <b>{sc('size')}:</b> {size}\n• <b>{sc('position')}:</b> {where}</blockquote>\n"
        f"<i>{sc('nudge the character, or replace it with another image.')}</i>"
    )


def char_kb(uid: int, mid: int, key: str) -> InlineKeyboardMarkup:
    c = lambda a: _cb(uid, mid, key, a)
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("Smaller", c("cminus"), None, "➖"), btn("Bigger", c("cplus"), None, "➕")],
        [btn("Left", c("cleft"), None, "⬅️"), btn("Right", c("cright"), None, "➡️")],
        [btn("Replace character", c("crep"), "character", "🔁")],
        [btn("Back", c("back"), "back", "↩️")],
    ])


# ---- special design: typed title ------------------------------------------
def title_text(t: dict | None) -> str:
    if not t:
        body = (f"• <b>{sc('mode')}:</b> automatic\n"
                f"• one line when the whole name fits, otherwise a small part and a big last word.")
    else:
        swap = t["swap"]
        rows = []
        for i, ln in enumerate(t["lines"][:3]):
            if i == 0:
                col = "left" if swap else "right"
            else:
                col = "right" if swap else "left"
            rows.append(f"<b>line {i + 1}</b> · {col} column · size {round(t['sizes'][i] * 100)}% · "
                        f"{t['shifts'][i]:+d}px\n   <code>{esc(ln)}</code>")
        body = "\n".join(rows) + f"\n• <b>{sc('gap between lines')}:</b> {t['gap']}px"
    return (
        f"<b>✏️ {sc('special design — title')}</b>\n\n<blockquote>{body}</blockquote>\n"
        f"<i>{sc('➖➕ = size, ⬆️⬇️ = position, for each line (L1, L2, L3). line 1 is the upper line when you tilt your head to read it.')}</i>\n"
        f"<i>{sc('a line can’t be longer than the poster is tall: if it runs off the edge, make it smaller, move it up, or split it into two lines.')}</i>"
    )


def title_kb(uid: int, mid: int, key: str, t: dict | None) -> InlineKeyboardMarkup:
    c = lambda a: _cb(uid, mid, key, a)
    rows = [[btn("Set title", c("ttlset"), "title", "✏️")]]
    if t:
        rows[0] += [btn("Auto", c("ttlauto"), None, "♻️"), btn("Swap sides", c("tswap"), None, "⇄")]
        for i in range(1, len(t["lines"][:3]) + 1):
            rows.append([
                btn(f"L{i}", c(f"tszm{i}"), None, "➖"), btn(f"L{i}", c(f"tszp{i}"), None, "➕"),
                btn(f"L{i}", c(f"tup{i}"), None, "⬆️"), btn(f"L{i}", c(f"tdn{i}"), None, "⬇️"),
            ])
        rows.append([btn("Gap −", c("tgm"), None, "↔️"), btn("Gap +", c("tgp"), None, "↔️")])
    rows.append([btn("Back", c("back"), "back", "↩️")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---- editable text --------------------------------------------------------
EDIT_LABELS = {"synopsis": "Synopsis", "genres": "Genres", "season_line": "Season line", "episodes_label": "Episode label"}
EDIT_ACTIONS = {"edf_syn": "synopsis", "edf_gen": "genres", "edf_sea": "season_line", "edf_epi": "episodes_label"}


def edit_text_view(ed: dict, anime: dict) -> str:
    def shown(field: str, current: str) -> str:
        mark = " ✏️" if field in ed else ""
        value = esc(current if len(current) <= 70 else current[:67] + "…") or "—"
        return f"• <b>{sc(EDIT_LABELS[field].lower())}</b>{mark}: {value}"

    rows = [shown("synopsis", ed.get("synopsis", anime.get("description", ""))),
            shown("genres", ed.get("genres", ", ".join(anime.get("genres4") or anime.get("genres") or []))),
            shown("season_line", ed.get("season_line", anime.get("season_line", ""))),
            shown("episodes_label", ed.get("episodes_label", anime.get("episodes_label", "")))]
    return (f"<b>📝 {sc('edit text')}</b>\n\n<blockquote>" + "\n".join(rows) + "</blockquote>\n"
            f"<i>{sc('fix anything AniList got wrong (sequels often are). ✏️ = your edit. applies to every design.')}</i>")


def edit_kb(uid: int, mid: int, key: str, ed: dict) -> InlineKeyboardMarkup:
    c = lambda a: _cb(uid, mid, key, a)
    rows = [[btn("Synopsis", c("edf_syn"), None, "📝"), btn("Genres", c("edf_gen"), None, "🏷")],
            [btn("Season line", c("edf_sea"), None, "📅"), btn("Episode label", c("edf_epi"), None, "🎞")]]
    if ed:
        rows.append([btn("Reset all text", c("edreset"), None, "♻️", "danger")])
    rows.append([btn("Back", c("menu"), "back", "↩️")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
