"""Focused tests for ``EventBus`` Pydantic models + state (Sprint 24 coverage ratchet).

Цель: поднять покрытие ``src/backend/infrastructure/clients/messaging/event_bus.py``
с ~38% до ≥60% путём тестирования Pydantic-моделей событий и базового
state-management EventBus без Redis (publish/subscribe требуют started broker).

Контракт API (см. event_bus.py):
- ``OrderEvent(order_id, action, payload)`` — order event payload.
- ``PipelineEvent(route_id, status, correlation_id, duration_ms)`` — pipeline event.
- ``FlagEvent(name, enabled)`` — feature flag change.
- ``RouteEvent(route_id, action)`` — route registration/removal.
- ``GenericEvent(topic, payload, correlation_id, timestamp)`` — generic DSL.
- ``EventBus.__init__(schema_registry)`` — broker=None, started=False, quota.
- ``EventBus.attach_schema_registry(registry)`` — bind schema registry.
- ``EventBus.health_check(*, mode='fast')`` — health probe (no broker needed).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.infrastructure.clients.messaging.event_bus import (
    EventBus,
    EventBusNotStartedError,
    EventSchemaValidationError,
    FlagEvent,
    GenericEvent,
    OrderEvent,
    PipelineEvent,
    RouteEvent,
)


class TestEventModels:
    """Pydantic event models — easy coverage, no Redis needed."""

    def test_order_event_minimal(self) -> None:
        """``OrderEvent`` создаётся только с обязательными полями."""
        ev = OrderEvent(order_id=123, action="created")
        assert ev.order_id == 123
        assert ev.action == "created"
        assert ev.payload == {}

    def test_order_event_with_payload(self) -> None:
        """``OrderEvent`` принимает произвольный payload dict."""
        ev = OrderEvent(
            order_id=1, action="completed", payload={"items": [1, 2, 3]}
        )
        assert ev.payload == {"items": [1, 2, 3]}

    def test_order_event_missing_required(self) -> None:
        """``OrderEvent`` без ``order_id`` или ``action`` → ValidationError."""
        with pytest.raises(ValidationError):
            OrderEvent(action="created")  # type: ignore[call-arg]
        with pytest.raises(ValidationError):
            OrderEvent(order_id=1)  # type: ignore[call-arg]

    def test_pipeline_event_minimal(self) -> None:
        """``PipelineEvent`` создаётся с минимальным набором полей."""
        ev = PipelineEvent(
            route_id="r-1", status="started", correlation_id="c-123"
        )
        assert ev.route_id == "r-1"
        assert ev.status == "started"
        assert ev.correlation_id == "c-123"
        assert ev.duration_ms is None

    def test_pipeline_event_with_duration(self) -> None:
        """``PipelineEvent.duration_ms`` опционально."""
        ev = PipelineEvent(
            route_id="r-1",
            status="completed",
            correlation_id="c-1",
            duration_ms=123.45,
        )
        assert ev.duration_ms == 123.45

    def test_pipeline_event_missing_required(self) -> None:
        """``PipelineEvent`` без route_id/status/correlation_id → ValidationError."""
        with pytest.raises(ValidationError):
            PipelineEvent(status="started", correlation_id="c-1")  # type: ignore[call-arg]

    def test_flag_event(self) -> None:
        """``FlagEvent`` с name и enabled."""
        ev = FlagEvent(name="dark_mode", enabled=True)
        assert ev.name == "dark_mode"
        assert ev.enabled is True

    def test_flag_event_disabled(self) -> None:
        """``FlagEvent.enabled=False`` сохраняется."""
        ev = FlagEvent(name="beta", enabled=False)
        assert ev.enabled is False

    def test_flag_event_missing_required(self) -> None:
        """``FlagEvent`` без name/enabled → ValidationError."""
        with pytest.raises(ValidationError):
            FlagEvent(name="x")  # type: ignore[call-arg]

    def test_route_event(self) -> None:
        """``RouteEvent`` с route_id и action."""
        ev = RouteEvent(route_id="r-42", action="registered")
        assert ev.route_id == "r-42"
        assert ev.action == "registered"

    def test_route_event_missing_required(self) -> None:
        """``RouteEvent`` без route_id/action → ValidationError."""
        with pytest.raises(ValidationError):
            RouteEvent(action="registered")  # type: ignore[call-arg]

    def test_generic_event_minimal(self) -> None:
        """``GenericEvent`` создаётся только с topic."""
        ev = GenericEvent(topic="my.topic")
        assert ev.topic == "my.topic"
        assert ev.payload is None
        assert ev.correlation_id is None
        assert ev.timestamp is None

    def test_generic_event_with_dict_payload(self) -> None:
        """``GenericEvent`` принимает dict payload."""
        ev = GenericEvent(topic="t", payload={"key": "value"})
        assert ev.payload == {"key": "value"}

    def test_generic_event_with_list_payload(self) -> None:
        """``GenericEvent`` принимает list payload."""
        ev = GenericEvent(topic="t", payload=[1, 2, 3])
        assert ev.payload == [1, 2, 3]

    def test_generic_event_with_scalar_payloads(self) -> None:
        """``GenericEvent`` принимает scalar payloads (str/int/float/bool)."""
        assert GenericEvent(topic="t", payload="hello").payload == "hello"
        assert GenericEvent(topic="t", payload=42).payload == 42
        assert GenericEvent(topic="t", payload=3.14).payload == 3.14
        assert GenericEvent(topic="t", payload=True).payload is True

    def test_generic_event_with_correlation_and_timestamp(self) -> None:
        """``GenericEvent`` с correlation_id и timestamp."""
        ev = GenericEvent(
            topic="t",
            payload={"x": 1},
            correlation_id="cid-1",
            timestamp=1234567890.0,
        )
        assert ev.correlation_id == "cid-1"
        assert ev.timestamp == 1234567890.0


class TestEventBusState:
    """EventBus state без started broker."""

    def test_init_no_registry(self) -> None:
        """``__init__`` без schema_registry."""
        eb = EventBus()
        assert eb._broker is None
        assert eb._started is False
        assert eb._schema_registry is None
        # QuotaTracker создан.
        assert eb._quota is not None

    def test_init_with_registry(self) -> None:
        """``__init__(schema_registry=...)`` сохраняет registry."""
        registry = object()
        eb = EventBus(schema_registry=registry)
        assert eb._schema_registry is registry

    def test_attach_schema_registry_replaces(self) -> None:
        """``attach_schema_registry()`` заменяет registry."""
        eb = EventBus()
        new_reg = object()
        eb.attach_schema_registry(new_reg)
        assert eb._schema_registry is new_reg

    def test_attach_schema_registry_none(self) -> None:
        """``attach_schema_registry(None)`` сбрасывает registry."""
        eb = EventBus(schema_registry=object())
        eb.attach_schema_registry(None)
        assert eb._schema_registry is None


class TestEventBusHealthCheck:
    """``health_check()`` без started broker."""

    async def test_health_check_fast_no_broker(self) -> None:
        """``health_check(mode='fast')`` без broker → статус degraded/unhealthy."""
        eb = EventBus()
        result = await eb.health_check(mode="fast")
        assert isinstance(result, dict)
        # Ключевые поля присутствуют.
        assert "status" in result or "healthy" in result or "broker" in result

    async def test_health_check_default_mode(self) -> None:
        """``health_check()`` без mode → default 'fast'."""
        eb = EventBus()
        result = await eb.health_check()
        assert isinstance(result, dict)

    async def test_health_check_deep(self) -> None:
        """``health_check(mode='deep')`` принимает deep mode."""
        eb = EventBus()
        result = await eb.health_check(mode="deep")
        assert isinstance(result, dict)


class TestEventBusErrors:
    """EventBusNotStartedError + EventSchemaValidationError."""

    def test_event_bus_not_started_error_message(self) -> None:
        """``EventBusNotStartedError`` — RuntimeError с понятным msg."""
        err = EventBusNotStartedError("bus not started")
        assert isinstance(err, RuntimeError)
        assert "bus not started" in str(err)

    def test_event_schema_validation_error_attributes(self) -> None:
        """``EventSchemaValidationError`` сохраняет channel/event_type/reason."""
        err = EventSchemaValidationError(
            channel="events.orders", event_type="OrderEvent", reason="missing field"
        )
        assert err.channel == "events.orders"
        assert err.event_type == "OrderEvent"
        assert err.reason == "missing field"
        assert "events.orders" in err.message
        assert "OrderEvent" in err.message
        assert "missing field" in err.message

    def test_event_schema_validation_error_inherits_base_error(self) -> None:
        """``EventSchemaValidationError`` — наследник ``BaseError``."""
        from src.backend.core.errors import BaseError

        err = EventSchemaValidationError(
            channel="c", event_type="E", reason="r"
        )
        assert isinstance(err, BaseError)


class TestEventBusValidateNoRegistry:
    """``_validate_event()`` без registry — no-op."""

    async def test_validate_event_no_registry_returns_none(self) -> None:
        """``_validate_event()`` без registry возвращает None (no-op)."""
        eb = EventBus()
        event = OrderEvent(order_id=1, action="created")
        result = eb._validate_event("events.orders", event)
        assert result is None
