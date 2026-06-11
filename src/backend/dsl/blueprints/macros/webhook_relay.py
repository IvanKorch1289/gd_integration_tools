from __future__ import annotations

"""S68 W1 - webhook_relay blueprint extracted from macros.py.

webhook relay blueprint (source + sink).
"""


from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors import DispatchActionProcessor


def webhook_relay(
    route_id: str,
    source: str,
    targets: list[str],
    *,
    parallel: bool = True,
    with_dead_letter: bool = True,
    description: str = "",
) -> Pipeline:
    """Webhook relay: 1 вход → N выходов с DLQ.

    Использует Recipient List для fan-out и Dead Letter Channel
    для обработки ошибок при доставке.

    Args:
        route_id: Уникальный идентификатор маршрута.
        source: Источник webhook (e.g., "webhook:/incoming").
        targets: Список target route_id для рассылки.
        parallel: Параллельная или последовательная доставка.
        with_dead_letter: Включить DLQ для недоставленных.
        description: Описание маршрута.

    Returns:
        Pipeline: Готовый relay pipeline.
    """
    builder = RouteBuilder.from_(
        route_id, source=source, description=description or f"Relay: {route_id}"
    )

    if with_dead_letter:
        builder = builder.dead_letter(
            processors=[DispatchActionProcessor(action="notify.send")]
        )

    builder = (
        builder.idempotent(lambda ex: ex.meta.correlation_id, ttl_seconds=3600)
        .recipient_list(lambda ex: targets, parallel=parallel)
        .log(f"Relayed to {len(targets)} targets")
    )
    return builder.build()
