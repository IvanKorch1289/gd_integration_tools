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
        except (AttributeError, TypeError, ValueError, ImportError, RuntimeError) as schema_exc:
            # cycle-9/D-AUDIT-915: narrow exceptions + observability.
            # AttributeError — model_cls не Pydantic, TypeError — schema
            # generation failed, ValueError — invalid field, ImportError —
            # forward-ref missing. Bare `except Exception` маскировал
            # unrelated runtime errors (KeyError, RuntimeError).
            import logging  # noqa: F401 — availability probe
            logging.getLogger(__name__).debug(
                "event_schemas.model_schema_failed",
                extra={
                    "subject": subject,
                    "model": model_cls.__name__,
                    "error": str(schema_exc),
                },
            )
            continue
        registry.register(
            SchemaEntry(
                kind=SchemaKind.EVENT,
                name=subject,
                spec_schema=schema,
                meta={"model": model_cls.__name__, "auto_registered": True},
            ),
        )
        count += 1
    return count
