"""In-memory storage для OutboxPublishVerifier (test/dev_light)."""

from __future__ import annotations

import asyncio
import time

from src.backend.core.outbox_verify.store.base import (
    OutboxPublishEntry,
    OutboxPublishState,
    OutboxPublishStore,
)


class InMemoryOutboxVerifyStore(OutboxPublishStore):
    """In-process dict-based publish verification storage."""

    def __init__(self) -> None:
        self._entries: dict[str, OutboxPublishEntry] = {}
        self._lock = asyncio.Lock()

    async def begin(self, event_id: str) -> tuple[OutboxPublishState, OutboxPublishEntry | None]:
        async with self._lock:
            existing = self._entries.get(event_id)
            if existing is not None:
                return existing.state, existing
            now = time.time()
            entry = OutboxPublishEntry(
                event_id=event_id,
                state=OutboxPublishState.PUBLISHING,
                created_at=now,
                attempts=1,
            )
            self._entries[event_id] = entry
            return OutboxPublishState.PENDING, None

    async def confirm(self, event_id: str, broker: str, broker_offset: str) -> None:
        async with self._lock:
            entry = self._entries.get(event_id)
            if entry is not None:
                entry.state = OutboxPublishState.DELIVERED
                entry.broker = broker
                entry.broker_offset = broker_offset
                entry.delivered_at = time.time()
                entry.last_error = None

    async def fail(self, event_id: str, error: str) -> None:
        async with self._lock:
            entry = self._entries.get(event_id)
            if entry is not None:
                entry.state = OutboxPublishState.FAILED
                entry.last_error = error
                entry.attempts += 1

    async def get(self, event_id: str) -> OutboxPublishEntry | None:
        async with self._lock:
            return self._entries.get(event_id)

    async def close(self) -> None:
        async with self._lock:
            self._entries.clear()

    def size(self) -> int:
        return len(self._entries)
