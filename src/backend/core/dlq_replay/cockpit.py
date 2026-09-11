"""DLQ Replay Cockpit — high-level API (Wave 1 P0 #4).

Основные операции:

    1. ``send_to_dlq(message, error, consumer, topic)`` → DLQ record.
       Failure class определяется автоматически через FailureTaxonomy.

    2. ``list_dlq(consumer=..., topic=..., failure_class=..., replayed=...)``
       → список records с фильтрами для UI.

    3. ``replay(record_id, operator)`` → re-publish через callback + audit.

    4. ``classify_failure(error)`` → FailureClass (exposed для diagnostics).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from src.backend.core.dlq_replay.failure_taxonomy import (
    FailureClass,
    FailureTaxonomy,
    classify_exception,
)
from src.backend.core.dlq_replay.store.base import DLQRecord, DLQStore

logger = logging.getLogger(__name__)

__all__ = (
    "DLQRecord",
    "DLQReplayService",
    "FailureClass",
    "ReplayCockpit",
    "get_dlq_replay",
)


# Replay callback: ``async def replay_fn(record) -> bool``.
ReplayFn = Callable[[DLQRecord], Awaitable[bool]]


class DLQReplayService:
    """Service для DLQ send/list/replay с taxonomy classification."""

    def __init__(
        self,
        store: DLQStore,
        taxonomy: FailureTaxonomy | None = None,
    ) -> None:
        self._store = store
        self._taxonomy = taxonomy or classify_exception.__globals__["_default_taxonomy"]

    @property
    def store(self) -> DLQStore:
        return self._store

    @property
    def taxonomy(self) -> FailureTaxonomy:
        return self._taxonomy

    async def send_to_dlq(
        self,
        *,
        message: Any,
        error: BaseException,
        consumer_id: str,
        topic: str,
        attempts: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> DLQRecord:
        """Классифицировать failure и добавить в DLQ."""
        failure_class = self._taxonomy.classify(error)
        record = DLQRecord(
            record_id=str(uuid.uuid4()),
            consumer_id=consumer_id,
            topic=topic,
            message=message,
            error=str(error),
            failure_class=failure_class,
            attempts=attempts,
            created_at=time.time(),
            metadata=metadata or {},
        )
        await self._store.add(record)
        logger.info(
            "DLQ: send_to_dlq record_id=%s consumer=%s topic=%s failure_class=%s",
            record.record_id,
            consumer_id,
            topic,
            failure_class.value,
        )
        return record

    async def list_dlq(
        self,
        *,
        consumer_id: str | None = None,
        topic: str | None = None,
        failure_class: FailureClass | None = None,
        replayed: bool | None = None,
    ) -> list[DLQRecord]:
        """Список records с фильтрами."""
        return await self._store.list(
            consumer_id=consumer_id,
            topic=topic,
            failure_class=failure_class,
            replayed=replayed,
        )

    async def replay(
        self,
        *,
        record_id: str,
        operator: str,
        replay_fn: ReplayFn,
    ) -> bool:
        """Replay record через callback. Returns success."""
        record = await self._store.get(record_id)
        if record is None:
            logger.warning("DLQ: replay record_id=%s not found", record_id)
            return False
        if record.replayed_at is not None:
            logger.warning(
                "DLQ: replay record_id=%s already replayed by %s",
                record_id,
                record.replayed_by,
            )
            return False
        try:
            success = await replay_fn(record)
        except Exception as exc:
            logger.error(
                "DLQ: replay record_id=%s failed: %s", record_id, exc
            )
            return False
        if success:
            await self._store.mark_replayed(record_id, operator)
            logger.info(
                "DLQ: replay record_id=%s by operator=%s success",
                record_id,
                operator,
            )
        return success

    def classify_failure(self, error: BaseException) -> FailureClass:
        """Public wrapper для taxonomy.classify."""
        return self._taxonomy.classify(error)


# Alias for clarity (UI-facing API).
ReplayCockpit = DLQReplayService


# Singleton.
_cockpit: DLQReplayService | None = None


def get_dlq_replay() -> DLQReplayService:
    """Module-level singleton accessor."""
    global _cockpit
    if _cockpit is None:
        from src.backend.core.dlq_replay.store.in_memory import InMemoryDLQStore

        _cockpit = DLQReplayService(store=InMemoryDLQStore())
    return _cockpit


def _set_dlq_replay(service: DLQReplayService | None) -> None:
    """Override singleton (DI)."""
    global _cockpit
    _cockpit = service


def reset_dlq_replay() -> None:
    """Reset singleton (test-only)."""
    global _cockpit
    _cockpit = None
