"""Protection for a public bot: per-user rate limiting and an optional allow-list."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class RateLimited(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry in {retry_after:.0f}s")
        self.retry_after = retry_after


class RateLimiter:
    """Sliding one-minute window. `per_minute` render 'points' per user; 0 disables the limit.
    Heavy actions (HD export, preview grid) cost more than a normal render."""

    def __init__(self, per_minute: int = 0, exempt: frozenset = frozenset()):
        self.per_minute, self.exempt = per_minute, exempt
        self._hits: dict[int, deque[tuple[float, int]]] = defaultdict(deque)

    def check(self, uid: int, cost: int = 1) -> None:
        if not self.per_minute or uid in self.exempt:
            return
        now, hits = time.monotonic(), self._hits[uid]
        while hits and now - hits[0][0] >= 60:
            hits.popleft()
        used = sum(c for _, c in hits)
        if used + cost > self.per_minute and hits:
            raise RateLimited(60 - (now - hits[0][0]))
        hits.append((now, cost))


class AllowListMiddleware(BaseMiddleware):
    """If ALLOWED_USER_IDS is set, everybody else gets a short polite refusal (admins are always allowed)."""

    def __init__(self, allowed: frozenset, admins: frozenset = frozenset()):
        self.allowed, self.admins = allowed, admins

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        if self.allowed and user and user.id not in self.allowed and user.id not in self.admins:
            if isinstance(event, CallbackQuery):
                await event.answer("This bot is private.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("🔒 This bot is private.")
            return None
        return await handler(event, data)
