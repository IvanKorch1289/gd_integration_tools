"""EventSourcing + CQRS — v21 §2.2 P0 gap.

Closes v21 gap #2: Event Sourcing / CQRS. Enterprise auditability через
immutable event log + CQRS separation of command/query.

Архитектура::

    ┌──────────────┐  command   ┌──────────────┐  events   ┌──────────────┐
    │ Command Bus  │──────────►│ Aggregates   │──────────►│ Event Store  │
    │ (write)      │            │ (domain)     │           │ (append-only)│
    └──────────────┘            └──────────────┘           └──────┬───────┘
                                                                  │ replay
                                                                  ▼
                                                           ┌──────────────┐
                                                           │ Projections  │
                                                           │ (read model) │
                                                           └──────┬───────┘
                                                                  │ query
                                                                  ▼
                                                           ┌──────────────┐
                                                           │ Query Bus    │
                                                           │ (read)       │
                                                           └──────────────┘

Components:
* :class:`Event` — immutable domain event (frozen dataclass)
* :class:`EventStore` — append-only event log (in-memory default)
* :class:`EventStoreProcessor` — capture events from exchange, append to store
* :class:`CQRSMixin` — chainable .command_bus() + .query_bus() в RouteBuilder

Outbox pattern (668 LOC в существующем коде) — partial event sourcing уже есть.
Этот модуль дополняет outbox dedicated EventStore + CQRS read/write separation.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = (
    "CQRSMixin",
    "CommandBus",
    "CommandHandler",
    "Event",
    "EventStore",
    "EventStoreProcessor",
    "EventStream",
    "Projection",
    "QueryBus",
    "QueryHandler",
    "get_event_store",
    "reset_event_store",
    "set_event_store",
)

_log = logging.getLogger(__name__)


# ── Event dataclass ─────────────────────────────────────────────────────


class EventStream(str, Enum):
    """Имя event stream / topic / aggregate type."""

    ORDER = "order"
    PAYMENT = "payment"
    INVENTORY = "inventory"
    USER = "user"
    AUDIT = "audit"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
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


# ── EventStore (in-memory append-only) ─────────────────────────────────


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
        self,
        projection: "Projection",
        *,
        since_timestamp: float | None = None,
    ) -> None:
        """Replay all events через projection (для rebuild read model)."""
        with self._lock:
            events = list(self._events)
        for ev in events:
            if since_timestamp is None or ev.timestamp >= since_timestamp:
                projection.apply(ev)


# ── Projection (read model) ─────────────────────────────────────────────


class Projection:
    """Base class для read-model projections.

    Subclass и override :meth:`apply` для stateful transformations.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def apply(self, event: Event) -> None:
        """Override в subclass: apply event к read-model state."""
        raise NotImplementedError


# ── Command Bus (write side) ────────────────────────────────────────────


CommandHandler = Callable[[dict[str, Any]], Awaitable[list[Event]]]


class CommandBus:
    """Routes commands → command handlers → events.

    Usage::

        async def place_order_handler(cmd: dict) -> list[Event]:
            order_id = cmd["order_id"]
            return [Event(
                aggregate_id=order_id,
                event_type="order.placed",
                stream=EventStream.ORDER,
                payload=cmd,
            )]

        bus = CommandBus()
        bus.register("place_order", place_order_handler)
        events = await bus.dispatch("place_order", {"order_id": "o-1", "items": [...]})
    """

    def __init__(self, event_store: EventStore | None = None) -> None:
        self._handlers: dict[str, CommandHandler] = {}
        self._store: EventStore = event_store or InMemoryEventStore()

    @property
    def event_store(self) -> EventStore:
        return self._store

    def register(self, command_type: str, handler: CommandHandler) -> None:
        if command_type in self._handlers:
            raise ValueError(
                f"command {command_type!r} already registered "
                f"(handlers: {list(self._handlers.keys())})"
            )
        self._handlers[command_type] = handler

    async def dispatch(
        self, command_type: str, payload: dict[str, Any]
    ) -> list[Event]:
        handler = self._handlers.get(command_type)
        if handler is None:
            raise KeyError(
                f"no handler for command {command_type!r} "
                f"(registered: {list(self._handlers.keys())})"
            )
        events = await handler(payload)
        for ev in events:
            self._store.append(ev)
        return events


# ── Query Bus (read side) ───────────────────────────────────────────────


QueryHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class QueryBus:
    """Routes queries → query handlers → result.

    Read-only: handlers не должны mutate state. Результат — query result
    (можно cached в projection / Redis).
    """

    def __init__(self) -> None:
        self._handlers: dict[str, QueryHandler] = {}

    def register(self, query_type: str, handler: QueryHandler) -> None:
        if query_type in self._handlers:
            raise ValueError(
                f"query {query_type!r} already registered "
                f"(handlers: {list(self._handlers.keys())})"
            )
        self._handlers[query_type] = handler

    async def dispatch(self, query_type: str, params: dict[str, Any]) -> Any:
        handler = self._handlers.get(query_type)
        if handler is None:
            raise KeyError(
                f"no handler for query {query_type!r} "
                f"(registered: {list(self._handlers.keys())})"
            )
        return await handler(params)


# ── EventStoreProcessor ─────────────────────────────────────────────────


class EventStoreProcessor(BaseProcessor):
    """Capture events from exchange, append к EventStore.

    Captures events из ``exchange.properties['events']`` (list of Event or dict)
    или ``exchange.in_message.body['events']`` (для incoming payloads с events).

    Events appended к module-level EventStore singleton (или injected).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        *,
        stream: EventStream | str = EventStream.CUSTOM,
        event_store: EventStore | None = None,
        aggregate_id_field: str = "aggregate_id",
        events_field: str = "events",
        event_type_field: str = "event_type",
        name: str | None = None,
    ) -> None:
        if isinstance(stream, str) and stream not in [s.value for s in EventStream]:
            raise ValueError(
                f"stream должен быть EventStream или known value, "
                f"получено {stream!r}"
            )
        super().__init__(name=name or f"event_store_{stream}")
        self._stream = (
            EventStream(stream) if isinstance(stream, str) else stream
        )
        self._store: EventStore = event_store or get_event_store()
        self._aggregate_id_field = aggregate_id_field
        self._events_field = events_field
        self._event_type_field = event_type_field

    @handle_processor_error
    async def process(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        """Capture events из body[events_field] или properties[events_field]."""
        # Source 1: exchange.properties['events']
        events_raw = exchange.properties.get(self._events_field)
        # Source 2: exchange.in_message.body[events_field]
        if events_raw is None:
            body = exchange.in_message.body
            if isinstance(body, dict):
                events_raw = body.get(self._events_field)

        if not events_raw:
            return  # no events → no-op

        if not isinstance(events_raw, list):
            raise TypeError(
                f"{self._events_field} должен быть list, "
                f"получено {type(events_raw).__name__}"
            )

        for ev_raw in events_raw:
            if isinstance(ev_raw, Event):
                self._store.append(ev_raw)
            elif isinstance(ev_raw, dict):
                # Auto-convert dict → Event
                aggregate_id = ev_raw.get(
                    self._aggregate_id_field, str(uuid.uuid4())
                )
                event_type = ev_raw.get(self._event_type_field, "unknown")
                payload = {
                    k: v
                    for k, v in ev_raw.items()
                    if k
                    not in (
                        self._aggregate_id_field,
                        self._event_type_field,
                        "event_id",
                        "version",
                        "timestamp",
                    )
                }
                self._store.append(
                    Event(
                        aggregate_id=aggregate_id,
                        event_type=event_type,
                        stream=self._stream,
                        payload=payload,
                    )
                )
            else:
                raise TypeError(
                    f"event должен быть Event или dict, "
                    f"получено {type(ev_raw).__name__}"
                )

        # Record count в exchange properties
        exchange.set_property("events_appended", len(events_raw))


# ── Module-level EventStore singleton (DI-friendly) ────────────────────


_store: EventStore | None = None
_store_lock = threading.Lock()


def get_event_store() -> EventStore:
    """Return module-level EventStore singleton."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = InMemoryEventStore()
    return _store


def set_event_store(store: EventStore) -> None:
    """Replace module-level EventStore singleton (для tests / production)."""
    global _store
    with _store_lock:
        _store = store


def reset_event_store() -> EventStore:
    """Reset к fresh in-memory store (только для tests).

    Также очищает старый store instance (если он был singleton).
    """
    global _store
    with _store_lock:
        if _store is not None and isinstance(_store, InMemoryEventStore):
            _store._events.clear()
            _store._by_aggregate.clear()
            _store._by_stream.clear()
        _store = InMemoryEventStore()
    return _store


# ── CQRSMixin ───────────────────────────────────────────────────────────


class CQRSMixin:
    """Mixin для :class:`RouteBuilder` — chainable ``.command_bus()`` / ``.query_bus()``.

    Stateless: ``self._add`` через MRO.
    """

    __slots__ = ()

    def event_store(
        self,
        *,
        stream: EventStream | str = EventStream.CUSTOM,
        event_store: EventStore | None = None,
        aggregate_id_field: str = "aggregate_id",
        events_field: str = "events",
    ) -> "RouteBuilder":
        """Добавить :class:`EventStoreProcessor` в pipeline.

        Args:
            stream: EventStream (order/payment/...) для routing.
            event_store: Custom store (default: module-level singleton).
            aggregate_id_field: Field name в dict → Event для aggregate_id.
            events_field: Field name в body/properties со list of events.
        """
        return self._add(  # type: ignore[attr-defined]
            EventStoreProcessor(
                stream=stream,
                event_store=event_store,
                aggregate_id_field=aggregate_id_field,
                events_field=events_field,
            )
        )
