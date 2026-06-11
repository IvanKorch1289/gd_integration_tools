from __future__ import annotations

"""S68 W1 - format_bridge blueprint extracted from macros.py.

format conversion bridge (JSON/XML/CSV/...).
"""


from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.pipeline import Pipeline


def format_bridge(
    route_id: str,
    source: str,
    from_format: str,
    to_format: str,
    target_action: str,
    *,
    description: str = "",
) -> Pipeline:
    """Format conversion bridge: receive → convert → forward.

    Конвертирует данные из одного формата в другой
    и пересылает в target action.

    Args:
        route_id: Уникальный идентификатор маршрута.
        source: Источник данных.
        from_format: Входной формат (json, xml, yaml, csv, msgpack).
        to_format: Выходной формат.
        target_action: Action для отправки конвертированных данных.
        description: Описание маршрута.

    Returns:
        Pipeline: Готовый конвертирующий pipeline.
    """
    return (
        RouteBuilder.from_(
            route_id,
            source=source,
            description=description or f"Bridge: {from_format}→{to_format}",
        )
        .normalize()
        .translate(from_format, to_format)
        .dispatch_action(target_action)
        .build()
    )
