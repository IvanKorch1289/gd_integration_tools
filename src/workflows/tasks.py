"""Prefect-tasks для order processing.

IL-WF3: модуль помечен DEPRECATED. Эквивалентные DSL processors —
``src/workflows/orders_dsl.py::_call_*`` + WorkflowBuilder spec'ы.
Cooldown удаления — H3_PLUS (2026-07-01+).
"""

import warnings
from typing import Any

from prefect import task

from src.core.config.settings import settings
from src.infrastructure.external_apis.logging_service import tasks_logger
from src.services.core.orders import get_order_service
from src.utilities.utils import utilities
from src.workflows.dicts import ProcessingResult
from src.workflows.utils import validate_order_id

__all__ = (
    "send_notification_task",
    "create_skb_order_task",
    "get_skb_order_result_task",
    "send_order_result_task",
)

warnings.warn(
    "`app.workflows.tasks` (Prefect @task) deprecated in IL-WF3. "
    "DSL durable processors: `app.workflows.orders_dsl._call_*`. "
    "Removal: H3_PLUS cooldown (2026-07-01+).",
    DeprecationWarning,
    stacklevel=2,
)


@task(
    name="send-notification",
    description="Отправляет электронное письмо по указанному адресу",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    retry_jitter_factor=1,
    timeout_seconds=10,
    log_prints=True,
)
async def send_notification_task(body: dict[str, Any]) -> dict[str, Any]:
    """
    Отправляет электронное письмо с использованием сервиса почты.

    Args:
        body (dict[str, Any]): Данные для отправки письма, включая:
            - to_emails (list): Список адресов получателей.
            - subject (str): Тема письма.
            - message (str): Текст сообщения.

    Returns:
        dict[str, Any]: Результат отправки письма.

    Raises:
        Exception: В случае ошибки при отправке письма.
    """
    from src.infrastructure.external_apis.mail import get_mail_service

    async with get_mail_service() as mail_service:
        return await mail_service.send_email(
            to_emails=body["to_emails"],
            subject=body["subject"],
            message=body["message"],
        )


@task(
    name="create-skb-order",
    description="Создает заказ в системе SKB с логикой повторных попыток",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    retry_jitter_factor=1,
    timeout_seconds=300,
    log_prints=True,
)
@validate_order_id
async def create_skb_order_task(order_data: dict[str, Any]) -> ProcessingResult | None:
    """
    Создает новый заказ в системе SKB с валидацией и повторными попытками.

    Args:
        order_data (dict[str, Any]): Данные заказа, включая:
            - id (str): Идентификатор заказа.

    Returns:
        ProcessingResult: Результат обработки с полями:
            - success (bool): Успешность операции.
            - order_id (str): Идентификатор заказа.
            - result_data (dict[str, Any]): Данные результата.
            - error_message (str): Сообщение об ошибке.

    Raises:
        ValueError: Если отсутствует обязательный параметр order_id.
        Exception: В случае ошибки при создании заказа.
    """
    try:
        result = await get_order_service().create_skb_order(order_id=order_data["id"])

        if result.get("response", {}).get("status_code", {}) == 200:
            return {
                "success": True,
                "order_id": order_data["id"],
                "result_data": result,
                "error_message": None,
            }
        return None
    except Exception as exc:
        tasks_logger.error(f"Ошибка создания заказа: {str(exc)}", exc_info=True)
        raise


@task(
    name="get-skb-order-result",
    description="Получает результат заказа в системе SKB с логикой повторных попыток",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    retry_jitter_factor=1,
    log_prints=True,
)
@validate_order_id
async def get_skb_order_result_task(
    order_data: dict[str, Any],
) -> ProcessingResult | None:
    """
    Получает результат заказа в системе SKB с валидацией и повторными попытками.

    Args:
        order_data (dict[str, Any]): Данные заказа, включая:
            - id (str): Идентификатор заказа.

    Returns:
        ProcessingResult: Результат обработки с полями:
            - success (bool): Успешность операции.
            - order_id (str): Идентификатор заказа.
            - result_data (dict[str, Any]): Данные результата.
            - error_message (str): Сообщение об ошибке.

    Raises:
        ValueError: Если отсутствует обязательный параметр order_id.
        Exception: В случае ошибки при получении результата.
    """
    try:
        result = await get_order_service().get_order_file_and_json_from_skb(
            order_id=order_data["id"]
        )

        message = await utilities.safe_get(result, "response.data.Message", "Ошибка")

        if not message:
            return ProcessingResult(
                success=True,
                order_id=order_data["id"],
                result_data=result,
                error_message=None,
            )
        return None
    except Exception as exc:
        tasks_logger.error(f"Ошибка получения результата: {str(exc)}", exc_info=True)
        raise


@task(
    name="send-order-result",
    description="Отправляет результат заказа во внешнюю систему с логикой повторных попыток",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    retry_jitter_factor=1,
    timeout_seconds=300,
    log_prints=True,
)
@validate_order_id
async def send_order_result_task(order_data: dict[str, Any]) -> ProcessingResult:
    """
    Отправляет результат заказа во внешнюю систему с валидацией и повторными попытками.

    Args:
        order_data (dict[str, Any]): Данные заказа, включая:
            - id (str): Идентификатор заказа.

    Returns:
        ProcessingResult: Результат обработки с полями:
            - success (bool): Успешность операции.
            - order_id (str): Идентификатор заказа.
            - result_data (dict[str, Any]): Данные результата.
            - error_message (str): Сообщение об ошибке.

    Raises:
        ValueError: Если отсутствует обязательный параметр order_id.
        Exception: В случае ошибки при отправке результата.
    """
    try:
        result = await get_order_service().send_order_data(order_id=order_data["id"])

        return {
            "success": True,
            "order_id": order_data["id"],
            "result_data": result,
            "error_message": None,
        }
    except Exception as exc:
        tasks_logger.error(f"Ошибка отправки результата: {str(exc)}", exc_info=True)
        raise
