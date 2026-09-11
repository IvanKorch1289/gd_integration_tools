"""In-memory storage для Inbox.

Single-process, asyncio.Lock-protected. Используется для:
- Unit/integration тестов (без PG).
- dev_light профиля.

Production → :class:`PostgresInboxStore` с UNIQUE constraint и
``INSERT ... ON CONFLICT DO NOTHING``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from src.backend.core.inbox.store.base import InboxEntry, InboxState, InboxStore


def _make_key(consumer_id: str, message_id: str) -> str:
    """Composite key для dict storage."""
    return f"{consumer_id}:{message_id}"


class InMemoryInboxStore(InboxStore):
    """In-process dict-based inbox storage."""

    def __init__(self) -> None:
        self._entries: dict[str, InboxEntry] = {}
        self._lock = asyncio.Lock()

    async def try_claim(
        self, consumer_id: str, message_id: str
    ) -> tuple[InboxState, InboxEntry | None]:
        """Атомарная попытка зарегистрировать entry."""
        async with self._lock:
            key = _make_key(consumer_id, message_id)
            existing = self._entries.get(key)
            if existing is not None:
                return existing.state, existing
            # Создаём новый entry в state RECEIVED.
            now = time.time()
            entry = InboxEntry(
                consumer_id=consumer_id,
                message_id=message_id,
                state=InboxState.RECEIVED,
                created_at=now,
                attempts=1,
            )
            self._entries[key] = entry
            return InboxState.MISSING, None  # MISSING сигнализирует "обрабатывай".

    async def commit(self, consumer_id: str, message_id: str) -> None:
        """``RECEIVED → COMMITTED``."""
        async with self._lock:
            key = _make_key(consumer_id, message_id)
            entry = self._entries.get(key)
            if entry is not None:
                entry.state = InboxState.COMMITTED
                entry.committed_at = time.time()
                entry.last_error = None

    async def fail(
        self, consumer_id: str, message_id: str, error: str
    ) -> None:
        """``RECEIVED → FAILED``, инкрементирует attempts, сохраняет error."""
        async with self._lock:
            key = _make_key(consumer_id, message_id)
            entry = self._entries.get(key)
            if entry is not None:
                entry.state = InboxState.FAILED
                entry.last_error = error
                entry.attempts += 1

    async def get(
        self, consumer_id: str, message_id: str
    ) -> InboxEntry | None:
        """Получить entry или None."""
        async with self._lock:
            return self._entries.get(_make_key(consumer_id, message_id))

    async def close(self) -> None:
        """Cleanup — clear all entries."""
        async with self._lock:
            self._entries.clear()

    # ─── Test helpers ───────────────────────────────────────────────

    def size(self) -> int:
        """Текущее количество entries (test-only)."""
        return len(self._entries)

    def clear(self) -> None:
        """Очистить все entries (test-only)."""
        self._entries.clear()
