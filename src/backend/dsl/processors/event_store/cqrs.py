from __future__ import annotations

"""S66 W1 — cqrs.py part of event_store decomp.

CQRS bus (Projection + CommandBus + QueryBus + CQRSMixin).

Classes: Projection, CommandBus, QueryBus, CQRSMixin.
"""

from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.processors.event_store.types import Event  # S66 W1: cross-import

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

_log = get_logger(__name__)

# ── Event dataclass ─────────────────────────────────────────────────────


class Projection:
    """Base class для read-model projections.

    Subclass и override :meth:`apply` для stateful transformations.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def apply(self, event: Event) -> None:
        """Override в subclass: apply event к read-model state."""
        raise NotImplementedError


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

    async def dispatch(self, command_type: str, payload: dict[str, Any]) -> list[Event]:
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


from src.backend.dsl.processors.event_store.types import (
    EventStream,  # S66 W1: cross-import
)


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
