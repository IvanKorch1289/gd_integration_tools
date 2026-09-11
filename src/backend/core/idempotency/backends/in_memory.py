"""In-memory backend для Idempotency Service.

Используется в:
- Unit/integration тестах (без Redis/PG).
- ``dev_light`` профиле (Wave 21.3c fallback).
- Single-process dev-mode.

Не сериализуется, не durable, теряется при рестарте процесса.
TTL реализован через ``time.monotonic()`` + lazy expiry при ``get()``.

Concurrency:
- ``asyncio.Lock`` на уровне backend (per-process).
- ``begin()`` использует ``if key in self._entries`` — атомарно в single event loop.
- Если нужно multi-process safety → переключиться на Redis/PG backend.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from src.backend.core.idempotency.backends.base import (
    IdempotencyBackend,
    IdempotencyEntry,
    IdempotencyOutcome,
)


class InMemoryIdempotencyBackend(IdempotencyBackend):
    """In-process dict-based backend (testing + dev_light)."""

    def __init__(self) -> None:
        self._entries: dict[str, IdempotencyEntry] = {}
        self._lock = asyncio.Lock()

    async def begin(self, key: str, ttl_seconds: int) -> IdempotencyOutcome:
        """Ставит PENDING marker (или возвращает LOCKED/COMMITTED)."""
        async with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                # Lazy TTL check.
                if self._is_expired(existing):
                    del self._entries[key]
                else:
                    return existing.state
            now = time.time()
            self._entries[key] = IdempotencyEntry(
                key=key,
                state=IdempotencyOutcome.PENDING,
                created_at=now,
                ttl_seconds=ttl_seconds,
            )
            return IdempotencyOutcome.PENDING

    async def commit(self, key: str, result: Any) -> None:
        """``PENDING → COMMITTED``, сохранить ``result``."""
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                # Race: TTL expired или explicit fail().
                # Re-create as COMMITTED (для replay).
                self._entries[key] = IdempotencyEntry(
                    key=key,
                    state=IdempotencyOutcome.COMMITTED,
                    result=result,
                    created_at=time.time(),
                    committed_at=time.time(),
                )
            else:
                entry.state = IdempotencyOutcome.COMMITTED
                entry.result = result
                entry.committed_at = time.time()

    async def fail(self, key: str, error: str | None = None) -> None:
        """``PENDING → MISSING`` (удалить marker)."""
        async with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.state == IdempotencyOutcome.PENDING:
                del self._entries[key]

    async def get(self, key: str) -> IdempotencyEntry | None:
        """Получить entry или None."""
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if self._is_expired(entry):
                del self._entries[key]
                return None
            return entry

    async def close(self) -> None:
        """Cleanup — clear all entries."""
        async with self._lock:
            self._entries.clear()

    def _is_expired(self, entry: IdempotencyEntry) -> bool:
        """TTL check — entry expired if older than ``ttl_seconds``."""
        if entry.committed_at is not None:
            age = time.time() - entry.committed_at
        else:
            age = time.time() - entry.created_at
        return age > entry.ttl_seconds

    # ─── Test helpers ───────────────────────────────────────────────

    def size(self) -> int:
        """Текущее количество entries (test-only)."""
        return len(self._entries)

    def clear(self) -> None:
        """Очистить все entries (test-only)."""
        self._entries.clear()
