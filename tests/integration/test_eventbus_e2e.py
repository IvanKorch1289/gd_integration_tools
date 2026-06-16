# ruff: noqa: S101
"""EventBus integration test — publish → subscribe → receive.

Verifies that EventBusFacade.subscribe_with_lifecycle() actually registers
a consumer that receives published events. Uses unittest.mock to avoid
requiring a real Redis instance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.messaging.eventbus_facade import EventBusFacade


@pytest.mark.integration
@pytest.mark.asyncio
async def test_subscribe_with_lifecycle_registers_handler() -> None:
    """subscribe_with_lifecycle() calls bus.subscribe() and tracks the subscription."""
    mock_bus = MagicMock(name="event_bus")
    mock_bus.subscribe = AsyncMock(name="bus.subscribe", return_value="handle")

    facade = EventBusFacade(mock_bus, plugin="test")

    handler = AsyncMock(name="handler")
    result = await facade.subscribe_with_lifecycle(
        "events.orders", handler, topic_pattern="orders.*", ack_mode="auto"
    )

    # Verify bus.subscribe was called
    mock_bus.subscribe.assert_awaited_once_with("events.orders", handler)

    # Verify subscription is tracked
    assert facade.subscription_count == 1
    assert result == "handle"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_delivers_to_subscribed_handler() -> None:
    """Publish event → handler receives it (simulated via mock bus)."""
    received_events: list[dict] = []

    async def tracking_handler(event: dict) -> None:
        received_events.append(event)

    mock_bus = MagicMock(name="event_bus")
    # When subscribe is called, store the handler
    stored_handler: AsyncMock | None = None

    async def fake_subscribe(channel: str, handler: AsyncMock) -> str:
        nonlocal stored_handler
        stored_handler = handler
        return "sub_handle"

    mock_bus.subscribe = AsyncMock(name="bus.subscribe", side_effect=fake_subscribe)

    # When publish is called, invoke the stored handler
    async def fake_publish(channel: str, event: MagicMock) -> None:
        if stored_handler is not None:
            await stored_handler({"channel": channel, "event": event.model_dump()})

    mock_bus.publish = AsyncMock(name="bus.publish", side_effect=fake_publish)

    facade = EventBusFacade(mock_bus, plugin="test")

    # Subscribe
    handler = AsyncMock(name="handler")
    await facade.subscribe_with_lifecycle("events.orders", handler)

    # Publish
    mock_event = MagicMock(name="event")
    mock_event.model_dump.return_value = {
        "topic": "orders.created",
        "payload": {"id": 1},
    }
    await facade.publish("events.orders", mock_event)

    # Verify handler was called
    handler.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unsubscribe_all_clears_tracking() -> None:
    """unsubscribe_all() clears all tracked subscriptions."""
    mock_bus = MagicMock(name="event_bus")
    mock_bus.subscribe = AsyncMock(name="bus.subscribe", return_value="handle")

    facade = EventBusFacade(mock_bus, plugin="test")

    # Add some subscriptions
    await facade.subscribe_with_lifecycle("events.orders", AsyncMock())
    await facade.subscribe_with_lifecycle("events.pipeline", AsyncMock())

    assert facade.subscription_count == 2

    # Unsubscribe all
    await facade.unsubscribe_all()

    assert facade.subscription_count == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_subscribe_with_lifecycle_error_raises_service_error() -> None:
    """subscribe_with_lifecycle() raises ServiceError on bus failure."""
    mock_bus = MagicMock(name="event_bus")
    mock_bus.subscribe = AsyncMock(
        name="bus.subscribe", side_effect=RuntimeError("bus down")
    )

    facade = EventBusFacade(mock_bus, plugin="test")

    with pytest.raises(Exception, match="eventbus subscribe failed"):
        await facade.subscribe_with_lifecycle("events.orders", AsyncMock())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_facade_subscribe_and_publish_integration() -> None:
    """Full flow: subscribe → publish → verify handler called with event data."""
    handler_calls: list[dict] = []

    async def recording_handler(event: dict) -> None:
        handler_calls.append(event)

    mock_bus = MagicMock(name="event_bus")
    stored_handlers: dict[str, AsyncMock] = {}

    async def fake_subscribe(channel: str, handler: AsyncMock) -> str:
        stored_handlers[channel] = handler
        return f"handle_{channel}"

    async def fake_publish(channel: str, event: MagicMock) -> None:
        if channel in stored_handlers:
            await stored_handlers[channel](
                {"channel": channel, "data": event.model_dump()}
            )

    mock_bus.subscribe = AsyncMock(side_effect=fake_subscribe)
    mock_bus.publish = AsyncMock(side_effect=fake_publish)

    facade = EventBusFacade(mock_bus, plugin="test")

    # Subscribe to two channels
    await facade.subscribe_with_lifecycle("events.orders", recording_handler)
    await facade.subscribe_with_lifecycle("events.pipeline", recording_handler)

    # Publish to orders
    orders_event = MagicMock()
    orders_event.model_dump.return_value = {"topic": "order.created", "id": 42}
    await facade.publish("events.orders", orders_event)

    # Publish to pipeline
    pipeline_event = MagicMock()
    pipeline_event.model_dump.return_value = {
        "topic": "pipeline.started",
        "route": "r1",
    }
    await facade.publish("events.pipeline", pipeline_event)

    # Verify both handlers were called
    assert len(handler_calls) == 2
    assert handler_calls[0]["channel"] == "events.orders"
    assert handler_calls[1]["channel"] == "events.pipeline"
