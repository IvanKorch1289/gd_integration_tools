"""In-memory polling-канал для :class:`InvocationResponse` (W22.3).

Используется как backend ``api`` — REST-клиент опрашивает результат
через ``GET /api/v1/invocations/{id}``. Хранит ответы в обычном
``dict``-store с ограничением размера и TTL для защиты от утечки памяти
в long-running процессе.

Для prod рекомендуется заменить на Redis/SQL backend; для dev_light
и unit-тестов — этот класс достаточен.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from time import monotonic
from typing import NamedTuple

from src.backend.core.interfaces.invocation_reply import (
    InvocationReplyChannel,
    ReplyChannelKind,
)
from src.backend.core.interfaces.invoker import InvocationResponse

__all__ = ("MemoryReplyChannel",)

#: Количество хранимых ответов, после которого начинается eviction
#: самых старых записей (LRU-FIFO). Защита от безграничного роста при
#: длительной работе процесса.
DEFAULT_MAX_ENTRIES: int = 10_000

#: TTL хранения ответа в секундах. По истечении ``fetch`` вернёт ``None``
#: и запись будет удалена при следующей операции.
DEFAULT_TTL_SECONDS: float = 600.0


class _Entry(NamedTuple):
    response: InvocationResponse
    expires_at: float


class MemoryReplyChannel(InvocationReplyChannel):
    """Polling backend: result доступен по invocation_id до истечения TTL."""

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = asyncio.Lock()

    @property
    def kind(self) -> ReplyChannelKind:
        return ReplyChannelKind.API

    async def send(self, response: InvocationResponse) -> None:
        async with self._lock:
            self._evict_expired()
            self._store[response.invocation_id] = _Entry(
                response=response, expires_at=monotonic() + self._ttl
            )
            self._store.move_to_end(response.invocation_id)
            if len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    async def fetch(self, invocation_id: str) -> InvocationResponse | None:
        async with self._lock:
            entry = self._store.get(invocation_id)
            if entry is None:
                return None
            if entry.expires_at <= monotonic():
                self._store.pop(invocation_id, None)
                return None
            return entry.response

    def _evict_expired(self) -> None:
        """Удаляет просроченные записи. Вызывается под lock."""
        now = monotonic()
        expired = [k for k, v in self._store.items() if v.expires_at <= now]
        for key in expired:
            self._store.pop(key, None)
