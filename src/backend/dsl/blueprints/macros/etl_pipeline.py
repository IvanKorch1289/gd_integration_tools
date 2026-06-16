"""S68 W1 - etl_pipeline blueprint extracted from macros.py.

ETL pipeline blueprint (extract-transform-load).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors import (
    DispatchActionProcessor,
    LogProcessor,
    RetryProcessor,
)


def etl_pipeline(
    route_id: str,
    source: str,
    extract_action: str,
    transform_fn: Callable[[Exchange[Any], Any], None],
    load_action: str,
    *,
    retry_attempts: int = 3,
    use_circuit_breaker: bool = True,
    normalize_schema: type | None = None,
    description: str = "",
) -> Pipeline:
    """ETL pipeline: extract → normalize → transform → load.

    Включает Circuit Breaker для защиты от каскадных сбоев,
    Normalizer для приведения данных к единому формату,
    и OnCompletion для уведомления о результате.

    Args:
        route_id: Уникальный идентификатор маршрута.
        source: Источник данных (e.g., "timer:60s", "internal:etl").
        extract_action: Action для извлечения данных.
        transform_fn: Функция трансформации.
        load_action: Action для загрузки данных.
        retry_attempts: Количество попыток при ошибке.
        use_circuit_breaker: Включить Circuit Breaker.
        normalize_schema: Pydantic-модель для нормализации.
        description: Описание маршрута.

    Returns:
        Pipeline: Готовый ETL pipeline.

    Example::

        pipeline = etl_pipeline(
            route_id="etl.orders",
            source="timer:300s",
            extract_action="external_db.query",
            transform_fn=transform_orders,
            load_action="analytics.insert_batch",
        )
    """
    builder = RouteBuilder.from_(
        route_id, source=source, description=description or f"ETL: {route_id}"
    )

    extract_proc = DispatchActionProcessor(action=extract_action)

    if use_circuit_breaker:
        builder = builder.circuit_breaker(
            processors=[
                RetryProcessor(processors=[extract_proc], max_attempts=retry_attempts)
            ],
            failure_threshold=5,
            recovery_timeout=60.0,
            fallback_processors=[LogProcessor(level="error")],
        )
    else:
        builder = builder.retry(processors=[extract_proc], max_attempts=retry_attempts)

    if normalize_schema:
        builder = builder.normalize(target_schema=normalize_schema)

    builder = (
        builder.process_fn(transform_fn)
        .dispatch_action(load_action)
        .on_completion(processors=[LogProcessor(level="info")])
    )
    return builder.build()
