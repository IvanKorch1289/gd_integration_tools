"""Workflow utilities для legacy Prefect flows.

IL-WF3: модуль помечен DEPRECATED. Новый путь — DSL durable workflows
(см. ``src/workflows/orders_dsl.py`` + ADR-031). Старая Prefect-логика
сохраняется до физического удаления ``prefect`` из pyproject.toml —
cooldown H3_PLUS (2026-07-01+), аналогично aiohttp/pandas/zeep.

Миграция: ``managed_pause(delay)`` → ``WorkflowBuilder.wait(duration_s=delay)``.
``validate_order_id`` → ``WorkflowBuilder.step(..., processors=[validate])``.
``handle_error`` → compensate_with в WorkflowBuilder.
"""

import warnings
from functools import wraps
from typing import Any, Callable

from prefect import suspend_flow_run

from app.infrastructure.external_apis.logging_service import tasks_logger

__all__ = ("managed_pause", "validate_order_id", "handle_error")

warnings.warn(
    "`app.workflows.utils` (Prefect-based) deprecated in IL-WF3. "
    "Use DSL durable workflows from `app.workflows.orders_dsl` + "
    "`app.infrastructure.workflow.builder.WorkflowBuilder` instead. "
    "This module will be removed in H3_PLUS (2026-07-01+).",
    DeprecationWarning,
    stacklevel=2,
)


async def managed_pause(delay_seconds: int):
    """
    Приостанавливает текущий flow run и планирует его автоматическое возобновление
    через указанное время. Использует нативный механизм Prefect (suspend_flow_run).
    В отличие от pause, suspend выгружает инфраструктуру из памяти.
    """
    try:
        tasks_logger.info(f"Suspending flow run for {delay_seconds} seconds...")

        # Нативная функция Prefect. Флоу автоматически проснется через delay_seconds.
        # В этот момент процесс/воркер будет освобожден для других задач.
        await suspend_flow_run(timeout=delay_seconds)

    except Exception as exc:
        # Исключения типа SuspendFlowRun поднимаются внутри Prefect для остановки
        # выполнения. Мы перехватываем только реальные ошибки.
        if "Suspend" not in str(type(exc)):
            tasks_logger.error(f"Error in managed_pause: {str(exc)}")
            raise
        raise


def validate_order_id(func: Callable) -> Callable:
    """
    Декоратор для проверки наличия order_id в аргументах задачи.
    """

    @wraps(func)
    async def wrapper(order_data: dict[str, Any], *args, **kwargs) -> Any:
        if not order_data.get("id"):
            raise ValueError("Отсутствует обязательный параметр order_id")
        return await func(order_data, *args, **kwargs)

    return wrapper


async def handle_error(
    email: str, subject: str, error: str, ident_data: str = None
) -> None:
    """
    Централизованная обработка ошибок.
    """
    from app.workflows.order_tasks import send_notification_task

    await send_notification_task(
        {"to_emails": email, "subject": subject, "message": f"{ident_data}: {error}"}
    )
    tasks_logger.error(f"{subject}: {error}")
