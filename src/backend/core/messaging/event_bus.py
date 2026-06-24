"""Capability-checked facade для event bus (S123 W3).

ADR-0207: services/schema_registry/event_schemas.py импортирует
``FlagEvent``, ``OrderEvent``, ``PipelineEvent``, ``UserEvent`` из
``infrastructure.clients.messaging.event_bus``.

Re-exports all event types + EventBus class. Public surface is
stable, but cross-layer access now goes через core/ facade.
"""

from __future__ import annotations

from src.backend.core.di.providers.infrastructure_facade import (  # noqa: F401
    get_event_bus_class as _get_event_bus_cls,
    get_event_schema_validation_error_class as _get_event_sve_cls,
    get_flag_event_class as _get_flag_event_cls,
    get_generic_event_class as _get_generic_event_cls,
    get_order_event_class as _get_order_event_cls,
    get_pipeline_event_class as _get_pipeline_event_cls,
    get_route_event_class as _get_route_event_cls,
    get_event_bus_factory as _get_event_bus_fn,
)
EventBus = _get_event_bus_cls()
EventSchemaValidationError = _get_event_sve_cls()
FlagEvent = _get_flag_event_cls()
GenericEvent = _get_generic_event_cls()
OrderEvent = _get_order_event_cls()
PipelineEvent = _get_pipeline_event_cls()
RouteEvent = _get_route_event_cls()
get_event_bus = _get_event_bus_fn()

__all__ = (
    "EventBus",
    "EventSchemaValidationError",
    "FlagEvent",
    "GenericEvent",
    "OrderEvent",
    "PipelineEvent",
    "RouteEvent",
    "get_event_bus",
)
