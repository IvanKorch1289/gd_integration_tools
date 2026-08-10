"""Unit-тесты EventBus schema validation hook (S13 K3 W3)."""


from __future__ import annotations

import pytest

from src.backend.infrastructure.clients.messaging.event_bus import (
    EventBus,
    EventBusNotStartedError,
    EventSchemaValidationError,
    OrderEvent,
)
from src.backend.services.schema_registry.event_schemas import (
    register_default_event_schemas,
)
from src.backend.services.schema_registry.registry import (
    SchemaEntry,
    SchemaKind,
    ServiceSchemaRegistry,
)


def test_schema_kind_event_exists() -> None:
    assert SchemaKind.EVENT.value == "event"


def test_register_default_event_schemas() -> None:
    registry = ServiceSchemaRegistry()
    count = register_default_event_schemas(registry)
    assert count == 4
    entry = registry.get(SchemaKind.EVENT, "events.events.orders.OrderEvent")
    assert entry is not None
    assert entry.spec_schema is not None
    assert "order_id" in entry.spec_schema["properties"]


@pytest.mark.asyncio
async def test_event_bus_no_registry_no_validation() -> None:
    bus = EventBus()
    # M2: publish now raises ``EventBusNotStartedError`` when called
    # before ``start()`` (was: silent warning + drop). Caller must
    # opt-in to fire-and-forget if needed.
    with pytest.raises(EventBusNotStartedError, match="events.orders"):
        await bus.publish(
            "events.orders", OrderEvent(order_id=1, action="created")
        )


@pytest.mark.asyncio
async def test_event_bus_with_registry_valid_payload() -> None:
    registry = ServiceSchemaRegistry()
    register_default_event_schemas(registry)
    bus = EventBus(schema_registry=registry)
    # Same M2 contract: raises when broker is not initialised.
    with pytest.raises(EventBusNotStartedError):
        await bus.publish(
            "events.orders", OrderEvent(order_id=42, action="created")
        )


@pytest.mark.asyncio
async def test_event_bus_with_registry_invalid_payload() -> None:
    registry = ServiceSchemaRegistry()
    # Регистрируем заведомо строгую схему для OrderEvent.
    registry.register(
        SchemaEntry(
            kind=SchemaKind.EVENT,
            name="events.events.orders.OrderEvent",
            spec_schema={
                "type": "object",
                "required": ["order_id", "action", "payload"],
                "properties": {
                    "order_id": {"type": "integer", "minimum": 100},
                    "action": {"type": "string", "enum": ["created", "completed"]},
                    "payload": {"type": "object"},
                },
            },
        )
    )
    bus = EventBus(schema_registry=registry)
    # Schema validation runs BEFORE the broker check, so the schema
    # error is the one that surfaces here.
    with pytest.raises(EventSchemaValidationError) as exc_info:
        await bus.publish("events.orders", OrderEvent(order_id=200, action="ghost"))
    assert exc_info.value.channel == "events.orders"
    assert exc_info.value.event_type == "OrderEvent"


@pytest.mark.asyncio
async def test_event_bus_no_schema_for_channel_no_validation() -> None:
    registry = ServiceSchemaRegistry()
    bus = EventBus(schema_registry=registry)
    # Канал без зарегистрированной схемы → schema check skipped, but
    # broker check still fires per M2.
    with pytest.raises(EventBusNotStartedError):
        await bus.publish(
            "events.orders", OrderEvent(order_id=1, action="created")
        )


def test_attach_schema_registry_late_binding() -> None:
    bus = EventBus()
    registry = ServiceSchemaRegistry()
    register_default_event_schemas(registry)
    bus.attach_schema_registry(registry)
    assert bus._schema_registry is registry
