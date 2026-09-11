"""OutboxPublishService — high-level API для publish verification (Wave 1 P0 #3).

Two-phase commit protocol:

    Phase 1 (PRE-PUBLISH):
        begin_publish(event_id) → ACQUIRED/DUPLICATE/IN_PROGRESS.

    Phase 2 (POST-PUBLISH):
        publish_with_verification(event_id, broker, payload) → OutboxPublishResult.
        - Вызывает broker.publish(payload).
        - Если success → confirm(event_id, broker, offset) → DELIVERED.
        - Если fail → fail(event_id, error) → FAILED → retry later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from src.backend.core.outbox_verify.store.base import (
    OutboxPublishEntry,
    OutboxPublishOutcome,
    OutboxPublishState,
    OutboxPublishStore,
)

logger = logging.getLogger(__name__)

__all__ = (
    "OutboxPublishResult",
    "OutboxPublishService",
    "get_outbox_publish_service",
)


@dataclass(slots=True)
class OutboxPublishResult:
    """Result of ``publish_with_verification()``."""

    outcome: OutboxPublishOutcome
    entry: OutboxPublishEntry | None = None
    broker_offset: str | None = None
    error: str | None = None


# Publisher signature: ``async def publisher(payload, context) -> (broker, offset)``.
PublishFn = Callable[[Any, dict[str, Any]], Awaitable[tuple[str, str]]]


class OutboxPublishService:
    """High-level coordinator для outbox publish verification."""

    def __init__(self, store: OutboxPublishStore) -> None:
        self._store = store

    @property
    def store(self) -> OutboxPublishStore:
        return self._store

    async def publish_with_verification(
        self,
        *,
        event_id: str,
        payload: Any,
        publisher: PublishFn,
        metadata: dict[str, Any] | None = None,
    ) -> OutboxPublishResult:
        """Publish через two-phase verification protocol.

        Args:
            event_id: Unique ID события (UUID/HASH).
            payload: Данные для публикации (передаётся в publisher).
            publisher: Async ``(payload, context) -> (broker, offset)``.
            metadata: Опциональная metadata (trace_id, ...).

        Returns:
            :class:`OutboxPublishResult` с outcome + broker_offset.

        """
        # Phase 1: Lock.
        state, entry = await self._store.begin(event_id)

        if state == OutboxPublishState.DELIVERED:
            # Уже доставлено — skip (idempotent).
            logger.debug(
                "Outbox: deduplicated event_id=%s broker_offset=%s",
                event_id,
                entry.broker_offset if entry else None,
            )
            return OutboxPublishResult(
                outcome=OutboxPublishOutcome.DUPLICATE,
                entry=entry,
                broker_offset=entry.broker_offset if entry else None,
            )

        if state == OutboxPublishState.PUBLISHING:
            # Concurrent publisher.
            logger.warning(
                "Outbox: in_progress event_id=%s (concurrent publisher)",
                event_id,
            )
            return OutboxPublishResult(
                outcome=OutboxPublishOutcome.IN_PROGRESS,
                entry=entry,
            )

        # state == PENDING → caller acquired lock → publish.
        context = {"event_id": event_id, "metadata": metadata or {}}
        try:
            broker, broker_offset = await publisher(payload, context)
        except Exception as exc:
            await self._store.fail(event_id, error=str(exc))
            failed_entry = await self._store.get(event_id)
            logger.info(
                "Outbox: publish failed event_id=%s err=%s",
                event_id,
                exc,
            )
            return OutboxPublishResult(
                outcome=OutboxPublishOutcome.FAILED,
                entry=failed_entry,
                error=str(exc),
            )

        # Phase 2: Confirm.
        await self._store.confirm(event_id, broker, broker_offset)
        confirmed_entry = await self._store.get(event_id)
        return OutboxPublishResult(
            outcome=OutboxPublishOutcome.ACQUIRED,
            entry=confirmed_entry,
            broker_offset=broker_offset,
        )


_service: OutboxPublishService | None = None


def get_outbox_publish_service() -> OutboxPublishService:
    """Singleton accessor."""
    global _service
    if _service is None:
        from src.backend.core.outbox_verify.store.in_memory import (
            InMemoryOutboxVerifyStore,
        )

        _service = OutboxPublishService(store=InMemoryOutboxVerifyStore())
    return _service


def _set_outbox_publish_service(service: OutboxPublishService | None) -> None:
    """Override singleton (DI)."""
    global _service
    _service = service


def reset_outbox_publish_service() -> None:
    """Reset singleton (test-only)."""
    global _service
    _service = None
