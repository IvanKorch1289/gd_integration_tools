"""S60 W2 — events.py part of cdc decomp.

Classes: CDCEvent, CDCSubscription.

CDCEvent (Pydantic-ish) + CDCSubscription (data classes).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import field
from typing import Any
from uuid import uuid4


class CDCEvent:
    """Стандартизированное CDC-событие."""

    operation: str  # INSERT / UPDATE / DELETE / UPSERT
    table: str
    timestamp: str
    profile: str
    new: dict[str, Any] | None = None
    old: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "table": self.table,
            "timestamp": self.timestamp,
            "profile": self.profile,
            "new": self.new,
            "old": self.old,
        }


class CDCSubscription:
    """Описание подписки на изменения."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    profile: str = ""
    tables: list[str] = field(default_factory=list)
    strategy: str = "polling"
    interval: float = 5.0
    batch_size: int = 100
    timestamp_column: str = "updated_at"
    channel: str | None = None
    callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    target_action: str | None = None
    active: bool = True
