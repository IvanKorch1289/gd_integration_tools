from __future__ import annotations

"""S68 W1 - safe_action blueprint extracted from macros.py.

safe action wrapper (retry + DLQ + audit).
"""


from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors import (
    DeadLetterProcessor,
    DispatchActionProcessor,
    LogProcessor,
    RetryProcessor,
)


def safe_action(
    route_id: str,
    action: str,
    *,
    source: str = "",
    max_retries: int = 3,
    dlq_action: str | None = None,
    timeout_seconds: float = 30.0,
    description: str = "",
) -> Pipeline:
    """Action с retry, timeout и optional dead-letter queue.

    Обёртка для любого action с production-ready обработкой ошибок:
    timeout → retry с exponential backoff → DLQ при исчерпании попыток.

    Args:
        route_id: Уникальный идентификатор маршрута.
        action: Имя action для выполнения.
        source: Источник.
        max_retries: Максимум попыток.
        dlq_action: Action для Dead Letter Queue (опционально).
        timeout_seconds: Таймаут на выполнение.
        description: Описание маршрута.

    Returns:
        Pipeline: Готовый pipeline с resilience-паттернами.
    """
    builder = RouteBuilder.from_(
        route_id,
        source=source or f"internal:{route_id}",
        description=description or f"Safe action: {action}",
    )

    action_processor = DispatchActionProcessor(action=action)

    if dlq_action:
        builder = builder.do_try(
            try_processors=[
                RetryProcessor(processors=[action_processor], max_attempts=max_retries)
            ],
            catch_processors=[
                LogProcessor(level="error"),
                DeadLetterProcessor(
                    processors=[DispatchActionProcessor(action=dlq_action)]
                ),
            ],
        )
    else:
        builder = builder.retry(processors=[action_processor], max_attempts=max_retries)

    return builder.build()
