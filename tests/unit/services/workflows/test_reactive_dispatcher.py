"""Unit-тесты ReactiveWorkflowDispatcher — Sprint 12 K3 W4."""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.workflows.reactive_dispatcher import (
    ReactiveTrigger,
    ReactiveWorkflowDispatcher,
)


@pytest.fixture
def facade_mock() -> Any:
    facade = MagicMock()
    facade.start = AsyncMock(return_value=MagicMock(workflow_id="wf-123"))
    return facade


@pytest.fixture
def bus_mock() -> Any:
    bus = MagicMock()
    handlers: dict[str, list[Any]] = {}

    async def subscribe(channel: str, handler: Any) -> Any:
        handlers.setdefault(channel, []).append(handler)
        return handler

    bus.subscribe = AsyncMock(side_effect=subscribe)
    bus._handlers = handlers
    return bus


@pytest.mark.asyncio
async def test_register_and_subscribe(facade_mock: Any, bus_mock: Any) -> None:
    dispatcher = ReactiveWorkflowDispatcher(
        workflow_facade=facade_mock, event_bus=bus_mock
    )
    dispatcher.register_trigger(
        workflow_id="wf-1",
        trigger=ReactiveTrigger(channel="events.orders.created", debounce_seconds=0),
    )
    await dispatcher.start()
    bus_mock.subscribe.assert_awaited()


@pytest.mark.asyncio
async def test_event_triggers_workflow_no_debounce(
    facade_mock: Any, bus_mock: Any
) -> None:
    dispatcher = ReactiveWorkflowDispatcher(
        workflow_facade=facade_mock, event_bus=bus_mock
    )
    dispatcher.register_trigger(
        workflow_id="wf-1",
        trigger=ReactiveTrigger(channel="events.orders.created", debounce_seconds=0),
    )
    await dispatcher.start()
    handler = bus_mock._handlers["events.orders.created"][0]

    await handler({"event_id": "ev-1", "amount": 100})
    facade_mock.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_debounce_collapses_multiple_events(
    facade_mock: Any, bus_mock: Any
) -> None:
    dispatcher = ReactiveWorkflowDispatcher(
        workflow_facade=facade_mock, event_bus=bus_mock
    )
    dispatcher.register_trigger(
        workflow_id="wf-debounce",
        trigger=ReactiveTrigger(channel="events.orders.created", debounce_seconds=0.05),
    )
    await dispatcher.start()
    handler = bus_mock._handlers["events.orders.created"][0]

    await handler({"event_id": "ev-1"})
    await handler({"event_id": "ev-2"})
    await handler({"event_id": "ev-3"})
    await asyncio.sleep(0.1)

    assert facade_mock.start.await_count == 1


@pytest.mark.asyncio
async def test_filter_blocks_event(facade_mock: Any, bus_mock: Any) -> None:
    dispatcher = ReactiveWorkflowDispatcher(
        workflow_facade=facade_mock, event_bus=bus_mock
    )
    dispatcher.register_trigger(
        workflow_id="wf-filter",
        trigger=ReactiveTrigger(
            channel="events.orders.created",
            filter_expr="amount > 1000",
            debounce_seconds=0,
        ),
    )
    await dispatcher.start()
    handler = bus_mock._handlers["events.orders.created"][0]

    await handler({"event_id": "ev-1", "amount": 100})
    await handler({"event_id": "ev-2", "amount": 5000})

    assert facade_mock.start.await_count == 1


@pytest.mark.asyncio
async def test_dedup_via_redis(facade_mock: Any, bus_mock: Any) -> None:
    redis = MagicMock()
    call_count = {"n": 0}

    async def fake_set(key: str, val: str, *, nx: bool, ex: int) -> bool:
        call_count["n"] += 1
        return call_count["n"] == 1

    redis.set = AsyncMock(side_effect=fake_set)
    dispatcher = ReactiveWorkflowDispatcher(
        workflow_facade=facade_mock, event_bus=bus_mock, redis_client=redis
    )
    dispatcher.register_trigger(
        workflow_id="wf-dedup",
        trigger=ReactiveTrigger(
            channel="events.orders.created", dedup_key="order_id", debounce_seconds=0
        ),
    )
    await dispatcher.start()
    handler = bus_mock._handlers["events.orders.created"][0]

    await handler({"order_id": "ord-1"})
    await handler({"order_id": "ord-1"})

    assert facade_mock.start.await_count == 1


@pytest.mark.asyncio
async def test_multiple_triggers_same_channel(facade_mock: Any, bus_mock: Any) -> None:
    dispatcher = ReactiveWorkflowDispatcher(
        workflow_facade=facade_mock, event_bus=bus_mock
    )
    dispatcher.register_trigger(
        "wf-a", ReactiveTrigger(channel="events.shared", debounce_seconds=0)
    )
    dispatcher.register_trigger(
        "wf-b", ReactiveTrigger(channel="events.shared", debounce_seconds=0)
    )
    await dispatcher.start()
    handler = bus_mock._handlers["events.shared"][0]

    await handler({"event_id": "ev"})
    assert facade_mock.start.await_count == 2


@pytest.mark.asyncio
async def test_graceful_shutdown_cancels_pending(
    facade_mock: Any, bus_mock: Any
) -> None:
    dispatcher = ReactiveWorkflowDispatcher(
        workflow_facade=facade_mock, event_bus=bus_mock
    )
    dispatcher.register_trigger(
        "wf-slow", ReactiveTrigger(channel="events.x", debounce_seconds=5)
    )
    await dispatcher.start()
    handler = bus_mock._handlers["events.x"][0]
    await handler({"event_id": "ev"})

    await dispatcher.stop()
    assert dispatcher._pending == {}
    facade_mock.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_filter_blocks_event(facade_mock: Any, bus_mock: Any) -> None:
    dispatcher = ReactiveWorkflowDispatcher(
        workflow_facade=facade_mock, event_bus=bus_mock
    )
    dispatcher.register_trigger(
        "wf-invalid",
        ReactiveTrigger(
            channel="events.x", filter_expr="this.is.not.valid", debounce_seconds=0
        ),
    )
    await dispatcher.start()
    handler = bus_mock._handlers["events.x"][0]
    await handler({"event_id": "ev"})

    facade_mock.start.assert_not_awaited()
