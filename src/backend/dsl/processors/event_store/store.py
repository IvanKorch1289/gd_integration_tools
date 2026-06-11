from __future__ import annotations
"""S66 W1 — store.py part of event_store decomp.

event store (EventStore ABC + InMemoryEventStore impl).

Classes: EventStore, InMemoryEventStore.
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

from src.backend.dsl.processors.event_store.types import Event  # S66 W1: cross-import


if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_log = get_logger(__name__)

# ── Event dataclass ─────────────────────────────────────────────────────

class EventStore(Protocol):
    """Protocol для event store (DI-friendly)."""

    def append(self, event: Event) -> None: ...
    def load(self, aggregate_id: str) -> list[Event]: ...
    def load_stream(self, stream: EventStream) -> list[Event]: ...
    def list_all(self) -> list[Event]: ...
    def replay(
        self, projection: "Projection", *, since_timestamp: float | None = None
    ) -> None: ...

class InMemoryEventStore:
    """Thread-safe in-memory append-only event store.

    Production-замены:
    * PostgreSQL: ``events`` table с unique (aggregate_id, version) constraint
    * EventStoreDB (https://developers.eventstore.com/)
    * Kafka: per-stream topic с key=aggregate_id
    """

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._by_aggregate: dict[str, list[Event]] = {}
        self._by_stream: dict[EventStream, list[Event]] = {}
        self._lock = threading.Lock()

    def append(self, event: Event) -> None:
        with self._lock:
            # Optimistic concurrency: per-aggregate version monotonic
            existing = self._by_aggregate.get(event.aggregate_id, [])
            if existing and event.version <= existing[-1].version:
                raise ValueError(
                    f"version conflict for aggregate {event.aggregate_id!r}: "
                    f"got {event.version}, last is {existing[-1].version}"
                )
            self._events.append(event)
            self._by_aggregate.setdefault(event.aggregate_id, []).append(event)
            self._by_stream.setdefault(event.stream, []).append(event)
        _log.debug(
            "event appended: id=%s type=%s aggregate=%s v=%d",
            event.event_id,
            event.event_type,
            event.aggregate_id,
            event.version,
        )

    def load(self, aggregate_id: str) -> list[Event]:
        with self._lock:
            return list(self._by_aggregate.get(aggregate_id, []))

    def load_stream(self, stream: EventStream) -> list[Event]:
        with self._lock:
            return list(self._by_stream.get(stream, []))

    def list_all(self) -> list[Event]:
        with self._lock:
            return list(self._events)

    def replay(
        self, projection: "Projection", *, since_timestamp: float | None = None
    ) -> None:
        """Replay all events через projection (для rebuild read model)."""
        with self._lock:
            events = list(self._events)
        for ev in events:
            if since_timestamp is None or ev.timestamp >= since_timestamp:
                projection.apply(ev)

