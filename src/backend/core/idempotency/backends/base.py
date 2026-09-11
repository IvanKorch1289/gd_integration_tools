"""Backend interface + value types для Idempotency Service.

Контракт:
- ``begin(key, ttl)`` → ставит ``PENDING`` marker (lock) — два concurrent
  вызова с одним ключом получают ``IdempotencyOutcome.LOCKED`` для второго.
- ``commit(key, result)`` → фиксирует результат, ``PENDING → COMMITTED``.
- ``fail(key)`` → удаляет ``PENDING`` marker (разрешает retry).
- ``get(key)`` → возвращает entry или None.

State machine:

    MISSING  ──begin()──▶  PENDING  ──commit(result)──▶  COMMITTED
       ▲                      │
       │                      └──fail()──▶  MISSING (retry allowed)
       │
       └──commit/fail/got COMMITTED ──▶  return cached result (replay)
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class IdempotencyOutcome(str, enum.Enum):
    """Результат операции begin/commit/fail."""

    MISSING = "missing"  # ключ отсутствует
    PENDING = "pending"  # ключ существует в state PENDING (in-flight)
    COMMITTED = "committed"  # ключ зафиксирован с результатом
    LOCKED = "locked"  # ключ locked другим caller'ом (concurrent conflict)
    ERROR = "error"  # backend error (fail-open)


@dataclass(slots=True)
class IdempotencyEntry:
    """Запись idempotency state в backend.

    Attributes:
        key: Idempotency key (caller-provided).
        state: ``PENDING`` / ``COMMITTED``.
        result: Serialized result (JSON-compatible).
        error: Error message если fn raised (для ``fail``).
        created_at: Unix timestamp создания PENDING.
        committed_at: Unix timestamp фиксации (если COMMITTED).
        ttl_seconds: TTL для auto-expiry.

    """

    key: str
    state: IdempotencyOutcome
    result: Any = None
    error: str | None = None
    created_at: float = 0.0
    committed_at: float | None = None
    ttl_seconds: int = 86400  # 24h default
    metadata: dict[str, Any] = field(default_factory=dict)


class IdempotencyBackend(ABC):
    """Abstract backend interface для IdempotencyService."""

    @abstractmethod
    async def begin(self, key: str, ttl_seconds: int) -> IdempotencyOutcome:
        """Поставить PENDING marker для ``key``.

        Returns:
            ``PENDING`` — успешно (вызывающий caller может продолжать).
            ``LOCKED`` — другой caller уже держит PENDING (concurrent).
            ``COMMITTED`` — уже зафиксировано (caller должен replay).

        """

    @abstractmethod
    async def commit(self, key: str, result: Any) -> None:
        """``PENDING → COMMITTED``, сохранить ``result``."""

    @abstractmethod
    async def fail(self, key: str, error: str | None = None) -> None:
        """``PENDING → MISSING`` (удалить marker; разрешить retry).

        Args:
            key: Idempotency key.
            error: Optional error message (логируется для diagnostics).

        """

    @abstractmethod
    async def get(self, key: str) -> IdempotencyEntry | None:
        """Получить entry или None (MISSING)."""

    @abstractmethod
    async def close(self) -> None:
        """Закрыть backend (cleanup connections)."""
