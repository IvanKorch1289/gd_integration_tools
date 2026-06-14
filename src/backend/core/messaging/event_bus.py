"""Capability-checked facade для event bus (S123 W3).

ADR-0207: services/schema_registry/event_schemas.py импортирует
``FlagEvent``, ``OrderEvent``, ``PipelineEvent``, ``UserEvent`` из
``infrastructure.clients.messaging.event_bus``.

Re-exports all event types + EventBus class. Public surface is
stable, but cross-layer access now goes через core/ facade.
"""

from __future__ import annotations

from src.backend.infrastructure.clients.messaging.event_bus import (  # noqa: F401
    EventBus,
    EventSchemaValidationError,
    FlagEvent,
    OrderEvent,
    PipelineEvent,
    RouteEvent,
    get_event_bus,
)

__all__ = (
    "EventBus",
    "EventSchemaValidationError",
    "FlagEvent",
    "OrderEvent",
    "PipelineEvent",
    "RouteEvent",
    "get_event_bus",
)
