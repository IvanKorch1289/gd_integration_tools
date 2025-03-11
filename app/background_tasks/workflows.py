from typing import Any, Dict

from prefect import flow
from prefect.task_runners import ConcurrentTaskRunner

from app.background_tasks.tasks import (
    create_skb_order_task,
    get_skb_order_result_task,
    send_notification_task,
    send_order_result_task,
)
from app.background_tasks.utils import handle_error, managed_pause
from app.config.constants import consts
from app.config.settings import settings
from app.utils.errors import BaseError
from app.utils.logging_service import tasks_logger
from app.utils.utils import utilities


__all__ = (
    "get_skb_order_result_workflow",
    "send_notification_workflow",
    "create_skb_order_workflow",
    "order_processing_workflow",
)


async def _send_status_notification(
    email: str,
    order_id: str,
    action: str,
    result: Dict[str, Any],
    default_message: str,
    data_path: str,
) -> None:
    """Отправляет уведомление о статусе операции."""
    try:
        message = await utilities.safe_get(result, data_path, default_message)
        await send_notification_workflow(
            {
                "to_emails": [email],
                "subject": f"Статус {action} заказа",
                "message": f"Заказ {order_id}: {message}",
            }
        )
    except Exception as exc:
        error_msg = f"Ошибка отправки уведомления о {action}: {exc}"
        await _handle_order_error(email, order_id, action, error_msg)
        raise


async def _handle_order_error(
    email: str, order_id: str, action: str, error: str
) -> None:
    """Обрабатывает ошибки связанные с заказом."""
    await handle_error(
        email=email,
        ident_data=f"Заказ {order_id}",
        subject=f"Ошибка {action} заказа",
        error=error,
    )
    tasks_logger.error(f"Ошибка {action} заказа {order_id}: {error}")


@flow(
    name="send-notification-workflow",
    description="Отправляет письмо клиенту по указанному адресу электронной почты",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    persist_result=True,
    task_runner=ConcurrentTaskRunner,
)
async def send_notification_workflow(body: dict) -> None:
    """
    Отправляет письмо клиенту с экспоненциальной задержкой при повторах.

    Args:
        body (dict): Данные для отправки письма, включая адрес электронной почты и текст сообщения.

    Returns:
        None
    """
    try:
        await send_notification_task(body)
    except Exception as exc:
        tasks_logger.error(f"Error during sending mail: {str(exc)}")
        raise


@flow(
    name="create-skb-order-workflow",
    description="Создает новый заказ в системе SKB для клиента с указанным номером заказа",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    persist_result=True,
    task_runner=ConcurrentTaskRunner,
)
async def create_skb_order_workflow(order_data: dict) -> Dict[str, Any]:
    """
    Создает новый заказ в системе SKB с экспоненциальной задержкой при повторах.

    Args:
        body (dict): Данные заказа.

    Returns:
        Dict[str, Any]: Результат обработки заказа.
    """
    order_id = order_data.get("id", "UNKNOWN")
    email = order_data.get("email_for_answer")

    try:
        result = await create_skb_order_task(order_data)  # type: ignore

        if not result.get("success"):
            error_msg = result.get(
                "error_message", "Неизвестная ошибка создания"
            )
            await _handle_order_error(email, order_id, "создания", error_msg)
            raise

        await _send_status_notification(
            email,
            order_id,
            "создания",
            result,
            "Заказ успешно создан",
            "result_data.response.data.Data.Message",
        )
        return result
    except Exception as exc:
        error_msg = f"Ошибка процесса создания заказа {order_id}: {exc}"
        tasks_logger.error(error_msg)
        raise BaseError(error_msg) from exc


@flow(
    name="get-skb-order-result-workflow",
    description="Отправляет результат обработки заказа в системе SKB в очередь для чтения",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    persist_result=True,
    task_runner=ConcurrentTaskRunner,
)
async def get_order_result_workflow(order_data: dict) -> Dict[str, Any]:
    """
    Отправляет результат SKB с задержкой при повторах в очередь для чтения.

    Args:
        body (dict): Данные заказа.

    Returns:
        Dict[str, Any]: Результат отправки.
    """
    order_id = order_data.get("id", "UNKNOWN")
    email = order_data.get("email_for_answer")

    for attempt in range(1, consts.MAX_RESULT_ATTEMPTS + 1):
        try:
            result = await get_skb_order_result_task(order_data)  # type: ignore

            if result.get("success"):
                await _send_status_notification(
                    email,
                    order_id,
                    "обработки",
                    result,
                    "Заказ успешно обработан",
                    "result_data.response.data.Data.Message",
                )
                return result
            if attempt < consts.MAX_RESULT_ATTEMPTS:
                error_msg = f"Повторная попытка {attempt + 1}/{consts.MAX_RESULT_ATTEMPTS}"
            else:
                error_msg = f"Заказ {order_id}: достигнуто максимальное количество попыток"

            await _handle_order_error(email, order_id, "обработки", error_msg)

        except Exception as exc:
            error_msg = f"Попытка {attempt}/{consts.MAX_RESULT_ATTEMPTS} не удалась: {exc}"
            await _handle_order_error(email, order_id, "обработки", error_msg)
            if attempt == consts.MAX_RESULT_ATTEMPTS:
                raise
            await managed_pause(delay_seconds=consts.RETRY_DELAY)

    raise BaseError(
        f"Не удалось обработать заказ {order_id} после {consts.MAX_RESULT_ATTEMPTS} попыток"
    )


@flow(
    name="send-skb-order-result-task-workflow",
    description="Получает результат обработки заказа в системе SKB",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    persist_result=True,
    task_runner=ConcurrentTaskRunner,
)
async def get_skb_order_result_workflow(order_data: dict) -> Dict[str, Any]:
    """
    Получает результат обработки заказа в системе SKB с экспоненциальной задержкой при повторах.

    Args:
        body (dict): Данные заказа.

    Returns:
        Dict[str, Any]: Результат обработки заказа.
    """
    order_id = order_data.get("id", "UNKNOWN")
    email = order_data.get("email_for_answer")

    try:
        result = await send_order_result_task(order_data)  # type: ignore
        if not result.get("success"):
            error_msg = result.get(
                "error_message", "Неизвестная ошибка создания"
            )
            await _handle_order_error(email, order_id, "отправки", error_msg)
            raise

        return result
    except Exception as exc:
        error_msg = (
            f"Ошибка процесса отправум результата заказа {order_id}: {exc}"
        )
        tasks_logger.error(error_msg)
        raise BaseError(error_msg) from exc


@flow(
    name="order-processing-workflow",
    description="Оптимизированный процесс обработки заказов с улучшенной обработкой ошибок",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    task_runner=ConcurrentTaskRunner,
)
async def order_processing_workflow(  # type: ignore
    order_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Основной процесс обработки заказов, включающий:
    1. Создание заказа.
    2. Ожидание обработки.
    3. Получение результата.
    4. Отправку уведомлений.

    Args:
        order_data (Dict[str, Any]): Данные заказа, включая:
            - id (str): Идентификатор заказа.
            - email_for_answer (str): Адрес электронной почты для уведомлений.

    Returns:
        Dict[str, Any]: Результат обработки заказа.

    Raises:
        Exception: В случае критической ошибки в процессе обработки.
    """
    try:
        # Этап 1: Создание заказа
        await create_skb_order_workflow(order_data)

        # Этап 2: Ожидание обработки заказа
        await managed_pause(delay_seconds=consts.INITIAL_DELAY)

        # Этап 3: Получение результата обработки заказа
        await get_skb_order_result_workflow(order_data)

        # Этап 4: Отправка результата
        await get_skb_order_result_workflow(order_data)
    except Exception as exc:
        await handle_error(
            email=order_data.get("email_for_answer"),
            ident_data=f"Заказ {order_data.get("id", "UNKNOWN")}",
            subject="Критическая ошибка в процессе обработки",
            error=f"Неожиданная ошибка: {str(exc)}",
        )
        raise
