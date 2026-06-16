"""S66 W1 — store.py part of event_store decomp.

event store (EventStore ABC + InMemoryEventStore impl).

Classes: EventStore, InMemoryEventStore.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol

from src.backend.core.logging import get_logger
from src.backend.dsl.processors.event_store.types import (  # S66 W1: cross-import
    Event,
    EventStream,
)

if TYPE_CHECKING:
    from src.backend.dsl.processors.event_store.cqrs import Projection

    pass

_log = get_logger(__name__)

# ── Event dataclass ─────────────────────────────────────────────────────


class EventStore(Protocol):
    """Protocol для event store (DI-friendly)."""

    def append(self, event: Event) -> None:
        """Append event в store (с optimistic concurrency по per-aggregate version)."""
        ...

    def load(self, aggregate_id: str) -> list[Event]:
        """Вернуть все events для aggregate (in-order, version-monotonic)."""
        ...

    def load_stream(self, stream: EventStream) -> list[Event]:
        """Вернуть все events в stream (cross-aggregate)."""
        ...

    def list_all(self) -> list[Event]:
        """Вернуть все events в store (для full rebuild)."""
        ...

    def replay(
        self, projection: "Projection", *, since_timestamp: float | None = None
    ) -> None:
        """Replay events через projection (для rebuild read model с optional since_timestamp)."""
        ...


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
        """Append event с optimistic concurrency (version conflict → ValueError)."""
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
        """Return copy of events для aggregate (defensive copy)."""
        with self._lock:
            return list(self._by_aggregate.get(aggregate_id, []))

    def load_stream(self, stream: EventStream) -> list[Event]:
        """Return copy of events в stream."""
        with self._lock:
            return list(self._by_stream.get(stream, []))

    def list_all(self) -> list[Event]:
        """Return copy of all events в store."""
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
