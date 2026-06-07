"""Unit-тесты EventBus (broker lifecycle, publish, subscribe, request)."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.clients.messaging.event_bus import (
    EventBus,
    EventSchemaValidationError,
    FlagEvent,
    OrderEvent,
    PipelineEvent,
    RouteEvent,
    get_event_bus,
)


@pytest.fixture
def fake_redis_broker_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Подсовывает фейковый faststream.redis модуль с RedisBroker AsyncMock."""

    class _FakeBroker:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.start = AsyncMock()
            self.close = AsyncMock()
            self.publish = AsyncMock()
            self.subscriber = MagicMock(return_value=lambda handler: handler)

    fake_mod = type(sys)("faststream.redis")
    fake_mod.RedisBroker = _FakeBroker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faststream.redis", fake_mod)
    return fake_mod


@pytest.mark.unit
class TestEventModels:
    def test_order_event_defaults(self) -> None:
        event = OrderEvent(order_id=1, action="created")
        assert event.order_id == 1
        assert event.action == "created"
        assert event.payload == {}

    def test_pipeline_event_optional(self) -> None:
        event = PipelineEvent(route_id="r1", status="ok", correlation_id="c1")
        assert event.duration_ms is None

    def test_flag_event(self) -> None:
        event = FlagEvent(name="feat_x", enabled=True)
        assert event.name == "feat_x"
        assert event.enabled is True

    def test_route_event(self) -> None:
        event = RouteEvent(route_id="r1", action="registered")
        assert event.route_id == "r1"
        assert event.action == "registered"


@pytest.mark.unit
class TestEventSchemaValidationError:
    def test_attributes(self) -> None:
        exc = EventSchemaValidationError("ch", "OrderEvent", "bad")
        assert exc.channel == "ch"
        assert exc.event_type == "OrderEvent"
        assert exc.reason == "bad"
        # BaseError принимает *_, поэтому message остаётся пустым —
        # это особенность target-реализации, не баг теста.
        assert exc.message == ""


@pytest.mark.unit
class TestEventBusLifecycle:
    @pytest.mark.asyncio
    async def test_start_sets_broker_and_started(
        self, fake_redis_broker_module: Any
    ) -> None:
        bus = EventBus()
        await bus.start("redis://localhost:6379")
        assert bus._started is True
        assert bus._broker is not None
        bus._broker.start.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_stop_closes_broker(self, fake_redis_broker_module: Any) -> None:
        bus = EventBus()
        await bus.start()
        await bus.stop()
        assert bus._started is False
        bus._broker.close.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_stop_without_broker_is_noop(self) -> None:
        bus = EventBus()
        await bus.stop()  # does not raise


@pytest.mark.unit
class TestEventBusPublish:
    @pytest.mark.asyncio
    async def test_publish_when_not_started_logs_warning(self, caplog: Any) -> None:
        bus = EventBus()
        with caplog.at_level("WARNING"):
            await bus.publish("events.orders", OrderEvent(order_id=1, action="created"))
        assert "not started" in caplog.text

    @pytest.mark.asyncio
    async def test_publish_with_broker(self, fake_redis_broker_module: Any) -> None:
        bus = EventBus()
        await bus.start()
        event = OrderEvent(order_id=1, action="created")
        await bus.publish("events.orders", event)
        bus._broker.publish.assert_awaited_once_with(  # type: ignore[attr-defined]
            event.model_dump(), channel="events.orders"
        )

    @pytest.mark.asyncio
    async def test_publish_order_event(self, fake_redis_broker_module: Any) -> None:
        bus = EventBus()
        await bus.start()
        await bus.publish_order_event(order_id=42, action="completed", payload={"x": 1})
        call_args = bus._broker.publish.call_args  # type: ignore[attr-defined]
        assert call_args.kwargs["channel"] == "events.orders"
        assert call_args.args[0]["order_id"] == 42
        assert call_args.args[0]["action"] == "completed"

    @pytest.mark.asyncio
    async def test_publish_pipeline_event(self, fake_redis_broker_module: Any) -> None:
        bus = EventBus()
        await bus.start()
        await bus.publish_pipeline_event(
            route_id="r1", status_="done", correlation_id="c1", duration_ms=12.5
        )
        call_args = bus._broker.publish.call_args  # type: ignore[attr-defined]
        assert call_args.kwargs["channel"] == "events.pipeline"
        dumped = call_args.args[0]
        assert dumped["route_id"] == "r1"
        assert dumped["status"] == "done"
        assert dumped["duration_ms"] == 12.5

    @pytest.mark.asyncio
    async def test_publish_flag_event(self, fake_redis_broker_module: Any) -> None:
        bus = EventBus()
        await bus.start()
        await bus.publish_flag_event(name="flag_a", enabled=False)
        call_args = bus._broker.publish.call_args  # type: ignore[attr-defined]
        assert call_args.kwargs["channel"] == "events.flags"
        assert call_args.args[0]["name"] == "flag_a"

    @pytest.mark.asyncio
    async def test_publish_route_event(self, fake_redis_broker_module: Any) -> None:
        bus = EventBus()
        await bus.start()
        await bus.publish_route_event(route_id="r2", action="removed")
        call_args = bus._broker.publish.call_args  # type: ignore[attr-defined]
        assert call_args.kwargs["channel"] == "events.routes"
        assert call_args.args[0]["route_id"] == "r2"


@pytest.mark.unit
class TestEventBusSubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_when_not_started_returns_none(self, caplog: Any) -> None:
        bus = EventBus()
        with caplog.at_level("WARNING"):
            result = await bus.subscribe("events.orders", lambda x: x)
        assert result is None
        assert "not started" in caplog.text

    @pytest.mark.asyncio
    async def test_subscribe_with_broker(self, fake_redis_broker_module: Any) -> None:
        bus = EventBus()
        await bus.start()

        async def handler(event: dict[str, Any]) -> None:
            pass

        result = await bus.subscribe("events.orders", handler)
        assert result is handler
        bus._broker.subscriber.assert_called_once_with("events.orders")  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_subscribe_exception_returns_none(
        self, fake_redis_broker_module: Any
    ) -> None:
        bus = EventBus()
        await bus.start()
        bus._broker.subscriber.side_effect = RuntimeError("boom")  # type: ignore[attr-defined]
        result = await bus.subscribe("events.orders", lambda x: x)
        assert result is None


@pytest.mark.unit
class TestEventBusRequest:
    @pytest.mark.asyncio
    async def test_request_delegates_to_reply_channel(self) -> None:
        bus = EventBus()
        fake_instance = MagicMock()
        fake_instance.request = AsyncMock(return_value={"ok": True})

        fake_reply_channel = MagicMock()
        fake_reply_channel.instance = MagicMock(return_value=fake_instance)

        fake_mod = type(sys)(
            "src.backend.infrastructure.clients.messaging.reply_channel"
        )
        fake_mod.ReplyChannel = fake_reply_channel  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules,
            {"src.backend.infrastructure.clients.messaging.reply_channel": fake_mod},
        ):
            result = await bus.request(
                "target", {"data": 1}, timeout=5.0, correlation_id="cid"
            )

        assert result == {"ok": True}
        fake_reply_channel.instance.assert_called_once_with(bus)
        fake_instance.request.assert_awaited_once_with(
            target_channel="target",
            payload={"data": 1},
            timeout=5.0,
            correlation_id="cid",
        )


@pytest.mark.unit
class TestEventBusSingleton:
    def test_get_event_bus_returns_event_bus(self) -> None:
        bus = get_event_bus()
        assert isinstance(bus, EventBus)
