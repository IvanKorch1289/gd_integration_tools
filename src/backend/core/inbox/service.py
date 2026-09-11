"""InboxService — high-level API для consumer dedupe (Wave 1 P0 #2).

State machine:
1. ``process(consumer_id, message_id, handler, payload)``:
    - ``MISSING`` (новая) → выполнить handler → ``COMMITTED``.
    - ``COMMITTED`` (уже обработано) → ``DEDUPLICATED``, no-op.
    - ``RECEIVED`` (concurrent) → ``LOCKED``, no-op (retry later).
    - ``FAILED`` (retry) → выполнить handler → ``COMMITTED``.

2. Handler signature: ``async def handler(payload: Any, context: dict) -> Any``.
3. ``context`` содержит ``consumer_id``, ``message_id``, ``metadata``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from src.backend.core.inbox.store.base import (
    InboxEntry,
    InboxOutcome,
    InboxState,
    InboxStore,
)

logger = logging.getLogger(__name__)

__all__ = (
    "InboxConflict",
    "InboxError",
    "InboxHandler",
    "InboxResult",
    "InboxService",
    "get_inbox_service",
)


class InboxError(Exception):
    """Base exception для Inbox."""


class InboxConflict(InboxError):
    """Raised when concurrent processing для (consumer_id, message_id)."""


# Handler signature: ``async def handler(payload, context) -> result``.
InboxHandler = Callable[[Any, dict[str, Any]], Awaitable[Any]]


@dataclass(slots=True)
class InboxResult:
    """Result of ``InboxService.process()``.

    Attributes:
        outcome: ``COMMITTED`` / ``DEDUPLICATED`` / ``LOCKED`` / ``FAILED``.
        result: Handler result (если COMMITTED, иначе None).
        entry: InboxEntry после операции (для diagnostics).
        attempts: Сколько раз пытались обработать (после retry).

    """

    outcome: InboxOutcome
    result: Any = None
    entry: InboxEntry | None = None
    attempts: int = 0


class InboxService:
    """High-level inbox coordinator для at-least-once consumers."""

    def __init__(self, store: InboxStore) -> None:
        self._store = store

    @property
    def store(self) -> InboxStore:
        """Storage backend (для test introspection)."""
        return self._store

    async def process(
        self,
        *,
        consumer_id: str,
        message_id: str,
        handler: InboxHandler,
        payload: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> InboxResult:
        """Process a consumed message через inbox dedupe.

        Args:
            consumer_id: ID consumer'а (например, ``"order-consumer"``).
            message_id: ID сообщения (broker-provided; UUID/HASH).
            handler: Async callable ``async def handler(payload, context) -> result``.
            payload: Данные сообщения (передаётся в handler).
            metadata: Произвольная metadata (trace_id, headers, ...).

        Returns:
            :class:`InboxResult` с outcome + handler result + entry.

        """
        # 1. Try claim (atomic).
        state, entry = await self._store.try_claim(consumer_id, message_id)

        # 2. Уже обработано → skip.
        if state == InboxState.COMMITTED:
            logger.debug(
                "Inbox: deduplicated message consumer_id=%s message_id=%s",
                consumer_id,
                message_id,
            )
            return InboxResult(
                outcome=InboxOutcome.DEDUPLICATED,
                entry=entry,
                attempts=entry.attempts if entry else 0,
            )

        # 3. Concurrent processing → LOCKED.
        if state == InboxState.RECEIVED:
            logger.warning(
                "Inbox: locked — concurrent processing consumer_id=%s message_id=%s",
                consumer_id,
                message_id,
            )
            return InboxResult(
                outcome=InboxOutcome.LOCKED,
                entry=entry,
                attempts=entry.attempts if entry else 0,
            )

        # 4. FAILED → retry (новая попытка; commit при успехе).
        # 5. MISSING → новая обработка (entry уже зарегистрирован в try_claim).
        context = {
            "consumer_id": consumer_id,
            "message_id": message_id,
            "metadata": metadata or {},
            "attempts": (entry.attempts if entry else 0),
        }

        try:
            result = await handler(payload, context)
        except Exception as exc:
            await self._store.fail(consumer_id, message_id, error=str(exc))
            failed_entry = await self._store.get(consumer_id, message_id)
            logger.info(
                "Inbox: handler failed consumer_id=%s message_id=%s attempts=%s err=%s",
                consumer_id,
                message_id,
                failed_entry.attempts if failed_entry else "?",
                exc,
            )
            return InboxResult(
                outcome=InboxOutcome.FAILED,
                entry=failed_entry,
                attempts=failed_entry.attempts if failed_entry else 0,
            )

        # 6. Успех → COMMITTED.
        await self._store.commit(consumer_id, message_id)
        committed_entry = await self._store.get(consumer_id, message_id)
        return InboxResult(
            outcome=InboxOutcome.COMMITTED,
            result=result,
            entry=committed_entry,
            attempts=committed_entry.attempts if committed_entry else 1,
        )


# Singleton — lazy init с InMemory store (test/dev_light).
_service: InboxService | None = None


def get_inbox_service() -> InboxService:
    """Module-level singleton accessor (lazy init).

    Production code должен override через DI с PostgresInboxStore.
    """
    global _service
    if _service is None:
        from src.backend.core.inbox.store.in_memory import InMemoryInboxStore

        _service = InboxService(store=InMemoryInboxStore())
    return _service


def _set_inbox_service(service: InboxService | None) -> None:
    """Override singleton (для production wiring через DI)."""
    global _service
    _service = service


def reset_inbox_service() -> None:
    """Reset singleton (test-only)."""
    global _service
    _service = None
