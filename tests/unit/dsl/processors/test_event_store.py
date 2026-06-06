"""Unit tests for Event Sourcing / CQRS (v21 §2.2)."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.processors.event_store import (
    CommandBus,
    Event,
    EventStoreProcessor,
    EventStream,
    InMemoryEventStore,
    Projection,
    QueryBus,
    get_event_store,
    reset_event_store,
)


def _ex(body: Any = None, properties: dict[str, Any] | None = None) -> Exchange[Any]:
    exch = Exchange(
        in_message=Message(body=body, headers={}),
        out_message=Message(body=body, headers={}),
    )
    if properties:
        for k, v in properties.items():
            exch.set_property(k, v)
    return exch


# ── Event dataclass ─────────────────────────────────────────────────────


def test_event_defaults() -> None:
    ev = Event(aggregate_id="o-1", event_type="order.placed")
    assert ev.aggregate_id == "o-1"
    assert ev.event_type == "order.placed"
    assert ev.stream == EventStream.CUSTOM
    assert ev.version == 1
    assert ev.payload == {}
    assert ev.metadata == {}
    # Auto-generated IDs
    assert isinstance(ev.event_id, str)
    assert len(ev.event_id) > 0
    assert ev.timestamp > 0


def test_event_to_dict() -> None:
    ev = Event(
        aggregate_id="o-1",
        event_type="order.placed",
        payload={"total": 100.0},
        stream=EventStream.ORDER,
        version=2,
    )
    d = ev.to_dict()
    assert d["aggregate_id"] == "o-1"
    assert d["event_type"] == "order.placed"
    assert d["stream"] == "order"
    assert d["payload"] == {"total": 100.0}
    assert d["version"] == 2


# ── InMemoryEventStore ──────────────────────────────────────────────────


def test_event_store_append_and_load() -> None:
    store = InMemoryEventStore()
    ev1 = Event(aggregate_id="o-1", event_type="order.placed", version=1)
    ev2 = Event(aggregate_id="o-1", event_type="order.paid", version=2)
    store.append(ev1)
    store.append(ev2)
    events = store.load("o-1")
    assert len(events) == 2
    assert events[0] == ev1
    assert events[1] == ev2


def test_event_store_load_stream() -> None:
    store = InMemoryEventStore()
    store.append(Event(aggregate_id="o-1", event_type="order.placed", stream=EventStream.ORDER))
    store.append(Event(aggregate_id="p-1", event_type="payment.received", stream=EventStream.PAYMENT))
    orders = store.load_stream(EventStream.ORDER)
    payments = store.load_stream(EventStream.PAYMENT)
    assert len(orders) == 1
    assert len(payments) == 1
    assert orders[0].event_type == "order.placed"
    assert payments[0].event_type == "payment.received"


def test_event_store_version_conflict() -> None:
    store = InMemoryEventStore()
    store.append(Event(aggregate_id="o-1", event_type="order.placed", version=1))
    store.append(Event(aggregate_id="o-1", event_type="order.paid", version=2))
    # Try append with version <= existing
    with pytest.raises(ValueError, match="version conflict"):
        store.append(
            Event(aggregate_id="o-1", event_type="order.cancelled", version=2)
        )


def test_event_store_thread_safe() -> None:
    """Concurrent appends to different aggregates — no data loss."""
    import threading

    store = InMemoryEventStore()

    def append_many(start: int) -> None:
        for i in range(100):
            store.append(
                Event(
                    aggregate_id=f"a-{start + i}",
                    event_type="created",
                    version=1,
                )
            )

    threads = [threading.Thread(target=append_many, args=(i * 100,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.list_all()) == 500


# ── Projection ─────────────────────────────────────────────────────────


def test_projection_replay() -> None:
    store = InMemoryEventStore()
    store.append(
        Event(
            aggregate_id="o-1",
            event_type="order.placed",
            payload={"total": 100.0},
            version=1,
        )
    )
    store.append(
        Event(
            aggregate_id="o-1",
            event_type="order.paid",
            payload={"amount": 100.0},
            version=2,
        )
    )

    class OrderTotalsProjection(Projection):
        def __init__(self) -> None:
            super().__init__(name="order_totals")
            self.totals: dict[str, float] = {}

        def apply(self, event: Event) -> None:
            if event.event_type == "order.placed":
                self.totals[event.aggregate_id] = float(event.payload.get("total", 0))

    proj = OrderTotalsProjection()
    store.replay(proj)
    assert proj.totals == {"o-1": 100.0}


def test_projection_replay_since_timestamp() -> None:
    import time

    store = InMemoryEventStore()
    ev1 = Event(aggregate_id="o-1", event_type="order.placed", version=1)
    time.sleep(0.01)  # ensure different timestamps
    ev2 = Event(aggregate_id="o-1", event_type="order.paid", version=2)
    store.append(ev1)
    store.append(ev2)

    class CountProjection(Projection):
        def __init__(self) -> None:
            super().__init__(name="count")
            self.count = 0

        def apply(self, event: Event) -> None:
            self.count += 1

    proj = CountProjection()
    store.replay(proj, since_timestamp=ev2.timestamp)
    assert proj.count == 1  # только ev2 (>= ev2.timestamp)


# ── CommandBus ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_command_bus_dispatch() -> None:
    bus = CommandBus()

    async def place_order_handler(cmd: dict[str, Any]) -> list[Event]:
        return [
            Event(
                aggregate_id=cmd["order_id"],
                event_type="order.placed",
                stream=EventStream.ORDER,
                payload=cmd,
            )
        ]

    bus.register("place_order", place_order_handler)
    events = await bus.dispatch("place_order", {"order_id": "o-1", "total": 50.0})
    assert len(events) == 1
    # Event должен быть в store
    store_events = bus.event_store.load("o-1")
    assert len(store_events) == 1
    assert store_events[0].event_type == "order.placed"


@pytest.mark.asyncio
async def test_command_bus_unknown_command() -> None:
    bus = CommandBus()
    with pytest.raises(KeyError, match="no handler for command"):
        await bus.dispatch("unknown", {})


def test_command_bus_duplicate_register() -> None:
    bus = CommandBus()

    async def h1(cmd: dict[str, Any]) -> list[Event]:
        return []

    bus.register("cmd", h1)
    with pytest.raises(ValueError, match="already registered"):
        bus.register("cmd", h1)


# ── QueryBus ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_query_bus_dispatch() -> None:
    bus = QueryBus()

    async def get_order_handler(params: dict[str, Any]) -> dict[str, Any]:
        return {"order_id": params["order_id"], "status": "paid"}

    bus.register("get_order", get_order_handler)
    result = await bus.dispatch("get_order", {"order_id": "o-1"})
    assert result == {"order_id": "o-1", "status": "paid"}


@pytest.mark.asyncio
async def test_query_bus_unknown_query() -> None:
    bus = QueryBus()
    with pytest.raises(KeyError, match="no handler for query"):
        await bus.dispatch("unknown", {})


# ── EventStoreProcessor ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_processor_appends_from_properties() -> None:
    reset_event_store()
    proc = EventStoreProcessor(stream=EventStream.ORDER)
    exchange = _ex(
        body={},
        properties={
            "events": [
                {"aggregate_id": "o-1", "event_type": "order.placed", "total": 100.0},
            ]
        },
    )
    await proc.process(exchange, None)  # type: ignore[arg-type]

    store = get_event_store()
    events = store.load("o-1")
    assert len(events) == 1
    assert events[0].event_type == "order.placed"
    assert events[0].payload == {"total": 100.0}
    assert exchange.properties["events_appended"] == 1


@pytest.mark.asyncio
async def test_processor_appends_from_body() -> None:
    reset_event_store()
    proc = EventStoreProcessor(stream=EventStream.PAYMENT)
    exchange = _ex(
        body={
            "events": [
                {"aggregate_id": "p-1", "event_type": "payment.received", "amount": 50.0},
            ]
        }
    )
    await proc.process(exchange, None)  # type: ignore[arg-type]

    events = get_event_store().load("p-1")
    assert len(events) == 1
    assert events[0].stream == EventStream.PAYMENT


@pytest.mark.asyncio
async def test_processor_appends_event_object() -> None:
    """Pass Event objects directly в properties/events."""
    reset_event_store()
    proc = EventStoreProcessor()
    ev = Event(aggregate_id="o-1", event_type="custom.event")
    exchange = _ex(body={}, properties={"events": [ev]})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    events = get_event_store().load("o-1")
    assert len(events) == 1
    assert events[0] is ev  # same object passed through


@pytest.mark.asyncio
async def test_processor_no_events_noop() -> None:
    """No events в body/properties → no-op, no error."""
    reset_event_store()
    proc = EventStoreProcessor()
    exchange = _ex(body={"some": "data"})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert get_event_store().list_all() == []
    assert "events_appended" not in exchange.properties


@pytest.mark.asyncio
async def test_processor_rejects_non_list_events() -> None:
    proc = EventStoreProcessor()
    exchange = _ex(body={}, properties={"events": "not a list"})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    # Exception caught by @handle_processor_error → set on exchange
    assert exchange.error is not None
    assert "должен быть list" in exchange.error


@pytest.mark.asyncio
async def test_processor_rejects_invalid_event_type() -> None:
    proc = EventStoreProcessor()
    exchange = _ex(body={}, properties={"events": [42]})  # int — invalid
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.error is not None
    assert "должен быть Event или dict" in exchange.error


def test_processor_validates_stream() -> None:
    with pytest.raises(ValueError, match="stream должен быть EventStream"):
        EventStoreProcessor(stream="invalid_stream")  # type: ignore[arg-type]


# ── Module-level singleton ─────────────────────────────────────────────


def test_get_event_store_singleton() -> None:
    e1 = get_event_store()
    e2 = get_event_store()
    assert e1 is e2


def test_reset_event_store_returns_fresh() -> None:
    es = get_event_store()
    es.append(Event(aggregate_id="o-1", event_type="created"))
    fresh = reset_event_store()
    assert fresh is not es
    assert fresh.list_all() == []
    # Old store cleared
    assert es.list_all() == []


# ── Side effect classification ─────────────────────────────────────────


def test_processor_side_effects() -> None:
    from src.backend.core.types.side_effect import SideEffectKind

    proc = EventStoreProcessor()
    assert proc.side_effect == SideEffectKind.SIDE_EFFECTING
    assert proc.compensatable is False  # append-only, нельзя откатить
