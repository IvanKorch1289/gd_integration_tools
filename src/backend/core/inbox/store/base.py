"""Backend interface + value types для Inbox.

Контракт ``process(consumer_id, message_id, handler, payload)``:

    MISSING  ──try_claim()──▶  RECEIVED  ──commit()──▶  COMMITTED
       ▲                          │                       │
       │                          └──fail()──▶ FAILED    │ (replay)
       │                                                  │
       └────── replay (после commit) ──▶ DEDUPLICATED ────┘
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class InboxState(str, enum.Enum):
    """State machine для Inbox entries."""

    MISSING = "missing"  # entry не существует
    RECEIVED = "received"  # entry зарегистрирована, handler в процессе
    COMMITTED = "committed"  # handler успешно завершён
    FAILED = "failed"  # handler failed; retry pending


class InboxOutcome(str, enum.Enum):
    """Result of ``InboxService.process()``."""

    COMMITTED = "committed"  # handler выполнен и зафиксирован
    DEDUPLICATED = "deduplicated"  # повторная доставка — skip
    FAILED = "failed"  # handler raised — failed state
    LOCKED = "locked"  # concurrent processing — skip + retry later


@dataclass(slots=True)
class InboxEntry:
    """Запись inbox state в storage.

    Attributes:
        consumer_id: ID consumer'а (multi-consumer isolation).
        message_id: ID сообщения (broker-provided).
        state: ``RECEIVED`` / ``COMMITTED`` / ``FAILED``.
        attempts: Сколько раз пытались обработать.
        last_error: Последний error message.
        created_at: Unix timestamp создания.
        committed_at: Unix timestamp фиксации (если COMMITTED).
        metadata: произвольные metadata (trace_id, payload_hash, ...).

    """

    consumer_id: str
    message_id: str
    state: InboxState
    attempts: int = 0
    last_error: str | None = None
    created_at: float = 0.0
    committed_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class InboxStore(ABC):
    """Abstract storage interface для InboxService."""

    @abstractmethod
    async def try_claim(
        self, consumer_id: str, message_id: str
    ) -> tuple[InboxState, InboxEntry | None]:
        """Попытка зарегистрировать entry для ``(consumer_id, message_id)``.

        Returns:
            ``(MISSING, None)`` — caller должен выполнить handler.
            ``(RECEIVED, entry)`` — concurrent processing (skip).
            ``(COMMITTED, entry)`` — уже обработано (skip).
            ``(FAILED, entry)`` — был fail, можно retry.

        """

    @abstractmethod
    async def commit(self, consumer_id: str, message_id: str) -> None:
        """``RECEIVED → COMMITTED``."""

    @abstractmethod
    async def fail(
        self, consumer_id: str, message_id: str, error: str
    ) -> None:
        """``RECEIVED → FAILED``, инкрементирует attempts, сохраняет error."""

    @abstractmethod
    async def get(
        self, consumer_id: str, message_id: str
    ) -> InboxEntry | None:
        """Получить entry или None."""

    @abstractmethod
    async def close(self) -> None:
        """Закрыть storage."""
