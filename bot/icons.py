"""Animated button icons (Telegram custom emoji), with a safe fallback to plain emoji.

Telegram only accepts custom-emoji icons from bots whose owner has Premium. If it refuses,
`disable()` is called once and every later keyboard silently uses normal emoji instead.
"""
from __future__ import annotations

_ids: dict[str, str] = {}
_enabled = True


def configure(ids: dict[str, str]) -> None:
    global _ids
    _ids = dict(ids)


def get(slot: str | None) -> str | None:
    return _ids.get(slot) if (_enabled and slot) else None


def disable() -> None:
    global _enabled
    _enabled = False


def any_configured() -> bool:
    return bool(_ids) and _enabled
