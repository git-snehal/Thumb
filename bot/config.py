"""Settings. Priority: environment variables (VPS / Docker / .env)  >  settings.py (Colab)  >  defaults.

On a VPS put everything in `.env` (or real environment variables) and leave settings.py alone.
In Colab, where .env files aren't picked up, fill in settings.py instead. Values that still hold the
"PASTE..." placeholder are ignored, so a stock settings.py never shadows your environment.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # python-dotenv is optional; real environment variables always work
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)      # never overrides variables already set in the environment
except ImportError:
    pass

try:
    import settings as _settings
except ImportError:  # settings.py deleted: environment variables only
    _settings = None


def _raw(name: str):
    """Environment first, then settings.py. None when neither has a real value."""
    env = os.environ.get(name)
    if env is not None and env.strip() != "":
        return env
    if _settings is not None and hasattr(_settings, name):
        value = getattr(_settings, name)
        if value is not None and not (isinstance(value, str) and value.strip() == ""):
            return value
    return None


def _str(name: str, default: str = "") -> str:
    value = _raw(name)
    text = default if value is None else str(value).strip()
    return default if text.upper().startswith("PASTE") else text


def _bool(name: str, default: bool) -> bool:
    value = _raw(name)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _num(name: str, default: float, cast=float, lo=None, hi=None):
    value = _raw(name)
    try:
        out = cast(value) if value is not None else default
    except (TypeError, ValueError):
        out = default
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return out


def _ids(name: str) -> frozenset[int]:
    value = _raw(name)
    if value is None:
        return frozenset()
    if isinstance(value, (list, tuple, set, frozenset)):
        parts = [str(v) for v in value]
    else:
        parts = re.split(r"[,\s]+", str(value))
    return frozenset(int(p) for p in parts if p.lstrip("-").isdigit())


_get = _str      # kept for scripts that import it


def brand_name() -> str:
    return _str("BRAND_NAME")


def _icons() -> dict[str, str]:
    raw = getattr(_settings, "ICONS", {}) if _settings else {}
    extra = os.environ.get("ICONS")                  # optional JSON in the environment: {"template": "5368..."}
    if extra:
        try:
            raw = {**raw, **json.loads(extra)}
        except ValueError:
            pass
    return {k: str(v).strip() for k, v in raw.items() if str(v).strip()}


@dataclass(frozen=True)
class Config:
    bot_token: str
    brand_name: str
    brand_position: str
    fancy_text: bool
    auto_cutout: bool
    icons: dict[str, str]
    render_concurrency: int
    cache_ttl: int
    db_path: Path
    logo_position: str = "tl"
    special_defaults: bool = True
    wm_opacity: float = 0.11
    boxes_opacity: float = 1.0
    kill_old: bool = False
    tmdb_key: str = ""
    fanart_key: str = ""
    extra_art: bool = True                       # Jikan + Kitsu posters in the image rotation
    upscale_art: bool = True                     # clean enlargement of small covers
    title_logos: bool = True                     # real title logos (fanart.tv / TMDB) where a design supports them
    watermark_text: str = ""                     # visible owner watermark (empty = off)
    watermark_key: str = ""                      # secret for the invisible mark (empty = off)
    allowed_users: frozenset = frozenset()       # empty = anyone may use the bot
    admin_ids: frozenset = frozenset()           # never rate-limited, always allowed
    rate_limit: int = 20                         # render actions per user per minute (0 = unlimited)
    log_level: str = "INFO"
    templates_dir: Path = ROOT / "templates"
    assets_dir: Path = ROOT / "assets"
    overrides_file: Path = ROOT / "templates.json"
    logos_dir: Path = field(default=ROOT / "data" / "logos")

    @property
    def data_dir(self) -> Path:
        return self.db_path.parent

    @property
    def heartbeat_file(self) -> Path:
        return self.data_dir / "heartbeat"


def load() -> Config:
    token = _str("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN is not set. Put it in .env (VPS / Docker) or in settings.py (Colab).")
    if not re.fullmatch(r"\d{5,}:[\w-]{20,}", token):
        print("WARNING: BOT_TOKEN doesn't look like a Telegram token (expected 123456:ABC...). Check it.", file=sys.stderr)

    corner = lambda name, default: (_str(name, default).lower() if _str(name, default).lower() in ("tl", "tr", "bl", "br") else default)
    kill = _str("KILL_OLD_INSTANCES", "auto").lower()
    kill_old = any(k.startswith("COLAB_") for k in os.environ) if kill == "auto" else kill in ("1", "true", "yes", "on")
    db = Path(_str("DB_PATH", "data/bot.db"))
    db = db if db.is_absolute() else ROOT / db
    level = _str("LOG_LEVEL", "INFO").upper()
    return Config(
        bot_token=token,
        brand_name=brand_name(),
        brand_position=corner("BRAND_POSITION", "tr"),
        logo_position=corner("LOGO_POSITION", "tl"),
        special_defaults=_bool("SPECIAL_DEFAULTS", True),
        wm_opacity=_num("SPECIAL_WATERMARK_OPACITY", 0.11, float, 0.0, 1.0),
        boxes_opacity=_num("SPECIAL_BOXES_OPACITY", 1.0, float, 0.0, 1.0),
        kill_old=kill_old,
        tmdb_key=_str("TMDB_API_KEY"),
        fanart_key=_str("FANART_API_KEY"),
        extra_art=_bool("EXTRA_ART_SOURCES", True),
        upscale_art=_bool("UPSCALE_SMALL_ART", True),
        title_logos=_bool("TITLE_LOGOS", True),
        watermark_text=_str("WATERMARK_TEXT"),
        watermark_key=_str("WATERMARK_KEY"),
        fancy_text=_bool("FANCY_TEXT", True),
        auto_cutout=_bool("AUTO_CUTOUT", True),
        icons=_icons(),
        render_concurrency=_num("RENDER_CONCURRENCY", 2, int, 1, 16),
        cache_ttl=_num("CACHE_TTL", 3600, int, 60),
        allowed_users=_ids("ALLOWED_USER_IDS"),
        admin_ids=_ids("ADMIN_IDS"),
        rate_limit=_num("RATE_LIMIT_PER_MIN", 20, int, 0),
        log_level=level if level in ("DEBUG", "INFO", "WARNING", "ERROR") else "INFO",
        db_path=db,
        logos_dir=db.parent / "logos",
    )
