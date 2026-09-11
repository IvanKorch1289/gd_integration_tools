"""Outbox Publish Verifier — store interface + value types."""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class OutboxPublishState(str, enum.Enum):
    """State machine для outbox publish."""

    PENDING = "pending"  # ещё не опубликовано
    PUBLISHING = "publishing"  # в процессе публикации (lock)
    DELIVERED = "delivered"  # broker подтвердил (offset/ack)
    FAILED = "failed"  # broker reject / timeout


class OutboxPublishOutcome(str, enum.Enum):
    """Result of publish operation."""

    ACQUIRED = "acquired"  # lock получен, можно publish
    DUPLICATE = "duplicate"  # уже DELIVERED (skip)
    IN_PROGRESS = "in_progress"  # другой publisher уже публикует
    FAILED = "failed"  # ошибка при publish


@dataclass(slots=True)
class OutboxPublishEntry:
    """Запись state для outbox event."""

    event_id: str
    state: OutboxPublishState
    broker: str | None = None  # kafka / rabbit / ...
    broker_offset: str | None = None  # broker-specific offset
    attempts: int = 0
    last_error: str | None = None
    created_at: float = 0.0
    delivered_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class OutboxPublishStore(ABC):
    """Abstract storage для publish verification."""

    @abstractmethod
    async def begin(self, event_id: str) -> tuple[OutboxPublishState, OutboxPublishEntry | None]:
        """Lock для publish. Returns (state, entry).

        - (PENDING, None) → caller может publish.
        - (PUBLISHING, entry) → другой caller уже публикует.
        - (DELIVERED, entry) → уже доставлено (skip).
        - (FAILED, entry) → retry.
        """

    @abstractmethod
    async def confirm(self, event_id: str, broker: str, broker_offset: str) -> None:
        """``PUBLISHING → DELIVERED`` с broker offset."""

    @abstractmethod
    async def fail(self, event_id: str, error: str) -> None:
        """``PUBLISHING → FAILED``, инкрементирует attempts."""

    @abstractmethod
    async def get(self, event_id: str) -> OutboxPublishEntry | None:
        """Получить entry или None."""

    @abstractmethod
    async def close(self) -> None:
        """Закрыть storage."""
