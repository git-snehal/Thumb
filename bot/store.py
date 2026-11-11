"""Per-user customisation, kept in a small SQLite file."""
from __future__ import annotations

import asyncio
import io
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

_COLS = ("brand_text", "brand_off", "logo_path", "position", "font", "scheme", "logo_position", "title_lang", "title_logo")


@dataclass
class UserSettings:
    brand_text: str | None = None   # None = use the bot's default BRAND_NAME
    brand_off: bool = False         # True = user explicitly removed all branding
    logo_path: str | None = None
    position: str | None = None
    font: str | None = None
    scheme: str | None = None       # special-design colours: preset key, 'auto' or '#hex[,#hex]'
    logo_position: str | None = None
    title_lang: str | None = None   # None/'auto' = English then romaji, or 'english' / 'romaji' / 'native'
    title_logo: str | None = None   # 'off' = never use the real title logo (None = use it when there is one)


class Store:
    def __init__(self, db_path: Path, logos_dir: Path):
        self.db_path, self.logos_dir = Path(db_path), Path(logos_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logos_dir.mkdir(parents=True, exist_ok=True)
        self.chars_dir = self.db_path.parent / "characters"
        self.chars_dir.mkdir(parents=True, exist_ok=True)
        self.bg_dir = self.db_path.parent / "backgrounds"
        self.bg_dir.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS user_settings ("
                "user_id INTEGER PRIMARY KEY, brand_text TEXT, brand_off INTEGER DEFAULT 0, "
                "logo_path TEXT, position TEXT, font TEXT, scheme TEXT)"
            )
            cols = {r[1] for r in c.execute("PRAGMA table_info(user_settings)")}
            for col in ("scheme", "logo_position", "title_lang", "title_logo"):   # upgrade databases created by older versions
                if col not in cols:
                    c.execute(f"ALTER TABLE user_settings ADD COLUMN {col} TEXT")
            c.execute(
                "CREATE TABLE IF NOT EXISTS titles ("
                "user_id INTEGER, anime_id INTEGER, text TEXT, gap INTEGER DEFAULT 22, shift INTEGER DEFAULT 0, "
                "small REAL DEFAULT 0.5, ts REAL, PRIMARY KEY (user_id, anime_id))"
            )
            tcols = {r[1] for r in c.execute("PRAGMA table_info(titles)")}
            for col, typ in (("sizes", "TEXT"), ("shifts", "TEXT"), ("swap", "INTEGER DEFAULT 0")):
                if col not in tcols:           # upgrade databases created by older versions
                    c.execute(f"ALTER TABLE titles ADD COLUMN {col} {typ}")
            c.execute(
                "CREATE TABLE IF NOT EXISTS text_edits ("
                "user_id INTEGER, anime_id INTEGER, synopsis TEXT, genres TEXT, season_line TEXT, "
                "episodes_label TEXT, ts REAL, PRIMARY KEY (user_id, anime_id))"
            )
            ecols = {r[1] for r in c.execute("PRAGMA table_info(text_edits)")}
            if "badges" not in ecols:          # upgrade databases created by older versions
                c.execute("ALTER TABLE text_edits ADD COLUMN badges TEXT")
            c.execute(
                "CREATE TABLE IF NOT EXISTS backgrounds ("
                "user_id INTEGER, anime_id INTEGER, path TEXT, idx INTEGER DEFAULT 0, "
                "wide INTEGER DEFAULT 0, ts REAL, PRIMARY KEY (user_id, anime_id))"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS characters ("
                "user_id INTEGER, anime_id INTEGER, path TEXT, dx INTEGER DEFAULT 0, "
                "scale REAL DEFAULT 1.0, ts REAL, PRIMARY KEY (user_id, anime_id))"
            )
            ccols = {r[1] for r in c.execute("PRAGMA table_info(characters)")}
            if "src_idx" not in ccols:         # which fanart.tv candidate this is (NULL = the person's own upload)
                c.execute("ALTER TABLE characters ADD COLUMN src_idx INTEGER")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _get(self, uid: int) -> UserSettings:
        with self._conn() as c:
            row = c.execute(f"SELECT {','.join(_COLS)} FROM user_settings WHERE user_id=?", (uid,)).fetchone()
        if not row:
            return UserSettings()
        return UserSettings(row[0], bool(row[1]), row[2], row[3], row[4], row[5], row[6], row[7], row[8])

    def _update(self, uid: int, **fields) -> None:
        assert set(fields) <= set(_COLS)
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (uid,))
            if fields:
                sets = ",".join(f"{k}=?" for k in fields)
                c.execute(f"UPDATE user_settings SET {sets} WHERE user_id=?", (*fields.values(), uid))

    async def get(self, uid: int) -> UserSettings:
        return await asyncio.to_thread(self._get, uid)

    async def update(self, uid: int, **fields) -> None:
        await asyncio.to_thread(self._update, uid, **fields)

    # -- logos -------------------------------------------------------------
    def logo_file(self, uid: int) -> Path:
        return self.logos_dir / f"{uid}.png"

    def _save_logo(self, uid: int, raw: bytes) -> str:
        img = Image.open(io.BytesIO(raw))
        img.load()
        if img.width * img.height > 40_000_000:
            raise ValueError("Image is too large.")
        img = img.convert("RGBA")
        img.thumbnail((600, 300))
        path = self.logo_file(uid)
        img.save(path, "PNG")
        return str(path)

    async def save_logo(self, uid: int, raw: bytes) -> None:
        path = await asyncio.to_thread(self._save_logo, uid, raw)
        await self.update(uid, logo_path=path, brand_off=0)

    async def remove_brand(self, uid: int) -> None:
        self.logo_file(uid).unlink(missing_ok=True)
        await self.update(uid, brand_text=None, logo_path=None, brand_off=1)

    # -- characters (special design), one per user per anime -----------------
    MAX_CHARACTERS_PER_USER = 30

    def _save_character(self, uid: int, anime_id: int, png: bytes, src_idx: int | None = None) -> None:
        import time
        path = self.chars_dir / f"{uid}_{anime_id}.png"
        path.write_bytes(png)
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO characters (user_id, anime_id, path, dx, scale, ts, src_idx) VALUES (?,?,?,0,1.0,?,?)",
                      (uid, anime_id, str(path), time.time(), src_idx))
            old = c.execute("SELECT anime_id, path FROM characters WHERE user_id=? ORDER BY ts DESC LIMIT -1 OFFSET ?",
                            (uid, self.MAX_CHARACTERS_PER_USER)).fetchall()
            for aid, pth in old:             # keep storage bounded
                Path(pth).unlink(missing_ok=True)
                c.execute("DELETE FROM characters WHERE user_id=? AND anime_id=?", (uid, aid))

    def _get_character(self, uid: int, anime_id: int) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT path, dx, scale, src_idx FROM characters WHERE user_id=? AND anime_id=?",
                            (uid, anime_id)).fetchone()
        if not row or not Path(row[0]).is_file():
            return None
        return {"path": row[0], "dx": row[1], "scale": row[2], "src_idx": row[3]}

    def _adjust_character(self, uid: int, anime_id: int, dx: int, scale: float) -> None:
        with self._conn() as c:
            c.execute("UPDATE characters SET dx=?, scale=? WHERE user_id=? AND anime_id=?", (dx, scale, uid, anime_id))

    async def save_character(self, uid: int, anime_id: int, png: bytes, src_idx: int | None = None) -> None:
        await asyncio.to_thread(self._save_character, uid, anime_id, png, src_idx)

    async def get_character(self, uid: int, anime_id: int) -> dict | None:
        return await asyncio.to_thread(self._get_character, uid, anime_id)

    async def adjust_character(self, uid: int, anime_id: int, d_dx: int = 0, d_scale: float = 0.0) -> dict | None:
        ch = await self.get_character(uid, anime_id)
        if not ch:
            return None
        dx = max(-360, min(360, ch["dx"] + d_dx))
        scale = round(max(0.55, min(1.5, ch["scale"] + d_scale)), 2)
        await asyncio.to_thread(self._adjust_character, uid, anime_id, dx, scale)
        return {**ch, "dx": dx, "scale": scale}

    # -- background art (posters 2-10 and template 1), one choice per user per anime -----------------
    # idx: 0..n-1 = which TMDB image, -1 = the AniList cover. A custom image (path) wins over both.
    def _get_art(self, uid: int, anime_id: int) -> dict:
        with self._conn() as c:
            row = c.execute("SELECT path, idx, wide FROM backgrounds WHERE user_id=? AND anime_id=?",
                            (uid, anime_id)).fetchone()
        if not row:
            return {"path": None, "idx": 0, "wide": False}
        path = row[0] if row[0] and Path(row[0]).is_file() else None
        return {"path": path, "idx": row[1] or 0, "wide": bool(row[2]) and path is not None}

    def _set_art(self, uid: int, anime_id: int, **fields) -> None:
        import time
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO backgrounds (user_id, anime_id, idx, ts) VALUES (?,?,0,?)",
                      (uid, anime_id, time.time()))
            sets = ",".join(f"{k}=?" for k in fields) + ",ts=?"
            c.execute(f"UPDATE backgrounds SET {sets} WHERE user_id=? AND anime_id=?",
                      (*fields.values(), time.time(), uid, anime_id))
            old = c.execute("SELECT anime_id, path FROM backgrounds WHERE user_id=? AND path IS NOT NULL "
                            "ORDER BY ts DESC LIMIT -1 OFFSET ?", (uid, self.MAX_CHARACTERS_PER_USER)).fetchall()
            for aid, pth in old:             # keep storage bounded
                Path(pth).unlink(missing_ok=True)
                c.execute("UPDATE backgrounds SET path=NULL WHERE user_id=? AND anime_id=?", (uid, aid))

    async def get_art(self, uid: int, anime_id: int) -> dict:
        return await asyncio.to_thread(self._get_art, uid, anime_id)

    async def set_art_idx(self, uid: int, anime_id: int, idx: int) -> None:
        await asyncio.to_thread(self._set_art, uid, anime_id, idx=idx)

    async def save_background(self, uid: int, anime_id: int, jpeg: bytes, wide: bool) -> None:
        path = self.bg_dir / f"{uid}_{anime_id}.jpg"
        await asyncio.to_thread(path.write_bytes, jpeg)
        await asyncio.to_thread(self._set_art, uid, anime_id, path=str(path), wide=int(wide))

    async def remove_background(self, uid: int, anime_id: int) -> None:
        (self.bg_dir / f"{uid}_{anime_id}.jpg").unlink(missing_ok=True)
        await asyncio.to_thread(self._set_art, uid, anime_id, path=None, wide=0)

    # -- custom special-design title: up to 3 lines typed by the user, each with its own size and position -----
    MAX_TITLE_LINES = 3

    @staticmethod
    def _pad(values: list, default, n: int = 3) -> list:
        return (list(values) + [default] * n)[:n]

    def _get_title(self, uid: int, anime_id: int) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT text, gap, sizes, shifts, swap FROM titles WHERE user_id=? AND anime_id=?",
                            (uid, anime_id)).fetchone()
        if not row or not row[0]:
            return None
        sizes = self._pad([float(x) for x in (row[2] or "").split(",") if x], 1.0)
        shifts = self._pad([int(float(x)) for x in (row[3] or "").split(",") if x], 0)
        return {"lines": [ln for ln in row[0].split("\n") if ln.strip()], "gap": row[1], "sizes": sizes,
                "shifts": shifts, "swap": bool(row[4])}

    def _set_title(self, uid: int, anime_id: int, text: str) -> None:
        import time
        with self._conn() as c:
            c.execute("INSERT INTO titles (user_id, anime_id, text, ts) VALUES (?,?,?,?) "
                      "ON CONFLICT(user_id, anime_id) DO UPDATE SET text=excluded.text, ts=excluded.ts",
                      (uid, anime_id, text, time.time()))
            c.execute("DELETE FROM titles WHERE user_id=? AND anime_id NOT IN "
                      "(SELECT anime_id FROM titles WHERE user_id=? ORDER BY ts DESC LIMIT 40)", (uid, uid))

    def _clear_title(self, uid: int, anime_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM titles WHERE user_id=? AND anime_id=?", (uid, anime_id))

    def _adjust_title(self, uid: int, anime_id: int, d_gap: int, line: int | None, d_size: float, d_shift: int,
                      swap: bool) -> bool:
        t = self._get_title(uid, anime_id)
        if not t:
            return False
        gap, sizes, shifts, sw = t["gap"], t["sizes"], t["shifts"], t["swap"]
        gap = max(0, min(90, gap + d_gap))
        if line is not None and 0 <= line < self.MAX_TITLE_LINES:
            sizes[line] = round(max(0.3, min(2.0, sizes[line] + d_size)), 2)
            shifts[line] = max(-500, min(500, shifts[line] + d_shift))
        if swap:
            sw = not sw
        with self._conn() as c:
            c.execute("UPDATE titles SET gap=?, sizes=?, shifts=?, swap=? WHERE user_id=? AND anime_id=?",
                      (gap, ",".join(map(str, sizes)), ",".join(map(str, shifts)), int(sw), uid, anime_id))
        return True

    async def get_title(self, uid: int, anime_id: int) -> dict | None:
        return await asyncio.to_thread(self._get_title, uid, anime_id)

    async def set_title(self, uid: int, anime_id: int, lines: list[str]) -> None:
        await asyncio.to_thread(self._set_title, uid, anime_id, "\n".join(lines))

    async def clear_title(self, uid: int, anime_id: int) -> None:
        await asyncio.to_thread(self._clear_title, uid, anime_id)

    async def adjust_title(self, uid: int, anime_id: int, d_gap: int = 0, line: int | None = None,
                           d_size: float = 0.0, d_shift: int = 0, swap: bool = False) -> bool:
        """line is 0-based. Sizes are multipliers (30%-200%) of the automatic size; shifts are px up(-)/down(+)."""
        return await asyncio.to_thread(self._adjust_title, uid, anime_id, d_gap, line, d_size, d_shift, swap)


    # -- text the person has corrected for one anime (synopsis, genres, season line, episode label) ---------
    EDIT_FIELDS = ("synopsis", "genres", "season_line", "episodes_label", "badges")

    def _get_edits(self, uid: int, anime_id: int) -> dict:
        with self._conn() as c:
            row = c.execute("SELECT synopsis, genres, season_line, episodes_label, badges FROM text_edits "
                            "WHERE user_id=? AND anime_id=?", (uid, anime_id)).fetchone()
        return {f: v for f, v in zip(self.EDIT_FIELDS, row or ()) if v is not None}

    def _set_edit(self, uid: int, anime_id: int, field: str, value: str | None) -> None:
        import time
        assert field in self.EDIT_FIELDS
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO text_edits (user_id, anime_id, ts) VALUES (?,?,?)", (uid, anime_id, time.time()))
            c.execute(f"UPDATE text_edits SET {field}=?, ts=? WHERE user_id=? AND anime_id=?", (value, time.time(), uid, anime_id))
            c.execute("DELETE FROM text_edits WHERE synopsis IS NULL AND genres IS NULL AND season_line IS NULL "
                      "AND episodes_label IS NULL AND badges IS NULL")
            c.execute("DELETE FROM text_edits WHERE user_id=? AND anime_id NOT IN "
                      "(SELECT anime_id FROM text_edits WHERE user_id=? ORDER BY ts DESC LIMIT 60)", (uid, uid))

    def _clear_edits(self, uid: int, anime_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM text_edits WHERE user_id=? AND anime_id=?", (uid, anime_id))

    async def get_edits(self, uid: int, anime_id: int) -> dict:
        return await asyncio.to_thread(self._get_edits, uid, anime_id)

    async def set_edit(self, uid: int, anime_id: int, field: str, value: str | None) -> None:
        """value=None puts that field back to the original AniList text."""
        await asyncio.to_thread(self._set_edit, uid, anime_id, field, value)

    async def clear_edits(self, uid: int, anime_id: int) -> None:
        await asyncio.to_thread(self._clear_edits, uid, anime_id)
