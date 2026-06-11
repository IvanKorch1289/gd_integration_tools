from __future__ import annotations
"""S68 W1 - crud_with_audit blueprint extracted from macros.py.

CRUD with audit trail.
"""

from collections.abc import Callable
from typing import Any

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors import (
    DeadLetterProcessor,
    DispatchActionProcessor,
    LogProcessor,
    RetryProcessor,
)

def crud_with_audit(
    route_id_prefix: str,
    create_action: str,
    update_action: str,
    delete_action: str,
    *,
    event_channel: str = "events.orders",
    source_prefix: str = "internal",
    validate_model: type | None = None,
) -> list[Pipeline]:
    """CRUD pipelines с event publishing для аудита.

    Создаёт 3 маршрута (create/update/delete), каждый:
    - Валидирует входные данные (опционально)
    - Выполняет action
    - Публикует событие для аудита
    - Логирует результат

    Args:
        route_id_prefix: Префикс для route_id (e.g., "orders").
        create_action: Action для создания.
        update_action: Action для обновления.
        delete_action: Action для удаления.
        event_channel: Канал для публикации событий.
        source_prefix: Префикс источника.
        validate_model: Pydantic-модель для валидации.

    Returns:
        list[Pipeline]: Три pipeline (create, update, delete).
    """
    pipelines = []

    for op, action in [
        ("create", create_action),
        ("update", update_action),
        ("delete", delete_action),
    ]:
        builder = RouteBuilder.from_(
            f"{route_id_prefix}.{op}", source=f"{source_prefix}:{route_id_prefix}.{op}"
        )
        if validate_model and op in ("create", "update"):
            builder = builder.validate(validate_model)
        builder = (
            builder.dispatch_action(action)
            .publish_event(event_channel)
            .on_completion(processors=[LogProcessor(level="info")])
        )
        pipelines.append(builder.build())

    return pipelines
