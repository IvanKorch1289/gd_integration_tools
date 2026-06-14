"""Регистрация default event-schemas в :class:`ServiceSchemaRegistry` (S13 K3 W3).

Вызывается на startup из ``plugins/composition/setup_infra.py`` — после
инициализации EventBus подключает реестр и регистрирует схемы для 4
встроенных event-моделей (OrderEvent, PipelineEvent, FlagEvent, RouteEvent).
"""

from __future__ import annotations

from typing import Any

from src.backend.services.schema_registry.registry import (
    SchemaEntry,
    SchemaKind,
    ServiceSchemaRegistry,
)

__all__ = ("register_default_event_schemas",)


def register_default_event_schemas(registry: ServiceSchemaRegistry) -> int:
    """Регистрирует JSON-Schema для 4 встроенных EventBus event-моделей.

    Returns:
        int: Количество зарегистрированных entries.
    """
    from src.backend.core.messaging.event_bus import (
        FlagEvent,
        OrderEvent,
        PipelineEvent,
        RouteEvent,
    )

    items: list[tuple[str, type[Any]]] = [
        ("events.events.orders.OrderEvent", OrderEvent),
        ("events.events.pipeline.PipelineEvent", PipelineEvent),
        ("events.events.flags.FlagEvent", FlagEvent),
        ("events.events.routes.RouteEvent", RouteEvent),
    ]
    count = 0
    for subject, model_cls in items:
        try:
            schema = model_cls.model_json_schema()
        except Exception:
            continue
        registry.register(
            SchemaEntry(
                kind=SchemaKind.EVENT,
                name=subject,
                spec_schema=schema,
                meta={"model": model_cls.__name__, "auto_registered": True},
            )
        )
        count += 1
    return count
