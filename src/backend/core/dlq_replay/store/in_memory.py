"""In-memory DLQ store (test/dev_light)."""

from __future__ import annotations

import asyncio
import time

from src.backend.core.dlq_replay.failure_taxonomy import FailureClass
from src.backend.core.dlq_replay.store.base import DLQRecord, DLQStore


class InMemoryDLQStore(DLQStore):
    """In-memory реализация ``DLQStore``: список записей + фильтры."""

    def __init__(self) -> None:
        self._records: dict[str, DLQRecord] = {}
        self._lock = asyncio.Lock()

    async def add(self, record: DLQRecord) -> None:
        """Добавить запись об отказе в DLQ."""
        async with self._lock:
            self._records[record.record_id] = record

    async def list(
        self,
        *,
        consumer_id: str | None = None,
        topic: str | None = None,
        failure_class: FailureClass | None = None,
        replayed: bool | None = None,
    ) -> list[DLQRecord]:
        """Список записей с фильтрами (consumer/topic/class/replayed)."""
        async with self._lock:
            result = list(self._records.values())
        # Apply filters.
        if consumer_id is not None:
            result = [r for r in result if r.consumer_id == consumer_id]
        if topic is not None:
            result = [r for r in result if r.topic == topic]
        if failure_class is not None:
            result = [r for r in result if r.failure_class == failure_class]
        if replayed is True:
            result = [r for r in result if r.replayed_at is not None]
        elif replayed is False:
            result = [r for r in result if r.replayed_at is None]
        return result

    async def get(self, record_id: str) -> DLQRecord | None:
        """Получить запись по id; ``None`` если отсутствует."""
        async with self._lock:
            return self._records.get(record_id)

    async def mark_replayed(self, record_id: str, operator: str) -> None:
        """Пометить запись как переигранную (replay) оператором."""
        async with self._lock:
            record = self._records.get(record_id)
            if record is not None:
                record.replayed_at = time.time()
                record.replayed_by = operator

    async def close(self) -> None:
        """Освободить ресурсы хранилища (no-op для in-memory)."""
        async with self._lock:
            self._records.clear()

    def size(self) -> int:
        """Количество записей в хранилище."""
        return len(self._records)
