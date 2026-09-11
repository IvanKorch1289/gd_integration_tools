"""DLQ store interface + value types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.dlq_replay.failure_taxonomy import FailureClass


@dataclass(slots=True)
class DLQRecord:
    """DLQ record с full context для replay."""

    record_id: str
    consumer_id: str
    topic: str
    message: Any
    error: str
    failure_class: FailureClass
    attempts: int = 1
    created_at: float = 0.0
    replayed_at: float | None = None
    replayed_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DLQStore(ABC):
    """Abstract storage для DLQ records."""

    @abstractmethod
    async def add(self, record: DLQRecord) -> None:
        """Add DLQ record."""

    @abstractmethod
    async def list(
        self,
        *,
        consumer_id: str | None = None,
        topic: str | None = None,
        failure_class: FailureClass | None = None,
        replayed: bool | None = None,
    ) -> list[DLQRecord]:
        """List records с фильтрами."""

    @abstractmethod
    async def get(self, record_id: str) -> DLQRecord | None:
        """Получить record по ID."""

    @abstractmethod
    async def mark_replayed(
        self, record_id: str, operator: str
    ) -> None:
        """Mark record as replayed (audit)."""

    @abstractmethod
    async def close(self) -> None:
        """Закрыть storage."""
