from __future__ import annotations
"""S66 W1 — types.py part of event_store decomp.

core data types (EventStream + Event).

Classes: EventStream, Event.
"""

import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_log = get_logger(__name__)

# ── Event dataclass ─────────────────────────────────────────────────────

class EventStream(str, Enum):
    """Имя event stream / topic / aggregate type."""

    ORDER = "order"
    PAYMENT = "payment"
    INVENTORY = "inventory"
    USER = "user"
    AUDIT = "audit"
    CUSTOM = "custom"

class Event:
    """Immutable domain event.

    Attributes:
        event_id: UUID event (auto-generated if not provided).
        aggregate_id: ID агрегата (order_id, user_id, ...).
        event_type: Семантический тип (``"order.placed"``, ``"payment.refunded"``).
        stream: EventStream (для partitioning / routing).
        payload: Domain data.
        version: Aggregate version (для optimistic concurrency).
        timestamp: Unix timestamp (sec).
        metadata: Audit info (user_id, tenant_id, causation_id, ...).
    """

    aggregate_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    stream: EventStream = EventStream.CUSTOM
    version: int = 1
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "aggregate_id": self.aggregate_id,
            "event_type": self.event_type,
            "stream": self.stream.value,
            "payload": dict(self.payload),
            "version": self.version,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }

