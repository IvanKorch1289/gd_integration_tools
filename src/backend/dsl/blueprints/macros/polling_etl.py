from __future__ import annotations

"""S68 W1 - polling_etl blueprint extracted from macros.py.

polling-based ETL (interval trigger).
"""

from collections.abc import Callable
from typing import Any

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.pipeline import Pipeline


def polling_etl(
    route_id: str,
    source_action: str,
    transform_fn: Callable[[Exchange[Any], Any], None] | None = None,
    load_action: str = "analytics.insert_batch",
    *,
    interval_seconds: float = 60.0,
    sort_field: str | None = None,
    description: str = "",
) -> Pipeline:
    """Polling ETL: timer → poll → transform → sort → load.

    Периодически опрашивает источник данных, трансформирует
    и загружает в хранилище.

    Args:
        route_id: Уникальный идентификатор маршрута.
        source_action: Action для получения данных.
        transform_fn: Функция трансформации (опционально).
        load_action: Action для загрузки.
        interval_seconds: Интервал опроса в секундах.
        sort_field: Поле для сортировки перед загрузкой.
        description: Описание маршрута.

    Returns:
        Pipeline: Готовый polling ETL pipeline.
    """
    builder = (
        RouteBuilder.from_(
            route_id,
            source=f"timer:{interval_seconds}s",
            description=description or f"Polling ETL: {source_action}",
        )
        .timer(interval_seconds=interval_seconds)
        .poll(source_action)
    )

    if transform_fn:
        builder = builder.process_fn(transform_fn)

    if sort_field:
        builder = builder.sort(key_field=sort_field)

    builder = builder.dispatch_action(load_action).log("Polling ETL complete")
    return builder.build()
