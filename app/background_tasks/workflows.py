from typing import Any, Dict

from prefect import flow
from prefect.task_runners import ConcurrentTaskRunner

from app.background_tasks.tasks import (
    create_skb_order_task,
    get_skb_order_result_task,
    send_notification_task,
    send_order_result_task,
)
from app.background_tasks.utils import managed_pause
from app.config.constants import (
    INITIAL_DELAY,
    MAX_RESULT_ATTEMPTS,
    RETRY_DELAY,
)
from app.config.settings import settings
from app.utils.logging_service import tasks_logger
from app.utils.utils import utilities


__all__ = (
    "get_skb_order_result_workflow",
    "send_notification_workflow",
    "create_skb_order_workflow",
    "order_processing_workflow",
)


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
    await send_notification_task(body)


@flow(
    name="create-skb-order-workflow",
    description="Создает новый заказ в системе SKB для клиента с указанным номером заказа",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    persist_result=True,
    task_runner=ConcurrentTaskRunner,
)
async def create_skb_order_workflow(body: dict) -> Dict[str, Any]:
    """
    Создает новый заказ в системе SKB с экспоненциальной задержкой при повторах.

    Args:
        body (dict): Данные заказа.

    Returns:
        Dict[str, Any]: Результат обработки заказа.
    """
    try:
        return await create_skb_order_task(body)
    except Exception as exc:
        tasks_logger.error(f"Error during create_skb_order_workflow: {exc}")
        raise


@flow(
    name="get-skb-order-result-task-workflow",
    description="Получает результат обработки заказа в системе SKB",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    persist_result=True,
    task_runner=ConcurrentTaskRunner,
)
async def get_skb_order_result_workflow(body: dict) -> Dict[str, Any]:
    """
    Получает результат обработки заказа в системе SKB с экспоненциальной задержкой при повторах.

    Args:
        body (dict): Данные заказа.

    Returns:
        Dict[str, Any]: Результат обработки заказа.
    """
    try:
        return await get_skb_order_result_task(body)
    except Exception as exc:
        tasks_logger.error(
            f"Error during get_skb_order_result_workflow: {exc}"
        )
        raise


@flow(
    name="order-processing-workflow",
    description="Оптимизированный процесс обработки заказов с улучшенной обработкой ошибок",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    task_runner=ConcurrentTaskRunner,
)
async def order_processing_workflow(
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
    email = order_data.get("email_for_answer")
    order_id = order_data.get("id", "UNKNOWN")

    async def handle_error(subject: str, error: str) -> None:
        """
        Централизованная обработка ошибок.

        Args:
            subject (str): Тема ошибки.
            error (str): Сообщение об ошибке.

        Returns:
            None
        """
        if email:
            await send_notification_task(
                {
                    "to_emails": email,
                    "subject": subject,
                    "message": f"Заказ {order_id}: {error}",
                }
            )
        tasks_logger.error(f"{subject}: {error}")

    try:
        # Этап 1: Создание заказа
        creation_result = await create_skb_order_workflow(order_data)

        if not creation_result.get("success"):
            await handle_error(
                "Ошибка создания заказа",
                creation_result.get("error_message", "Неизвестная ошибка"),
            )
            return creation_result

        # Отправка уведомления об успешном создании заказа
        if email:
            try:
                message = await utilities.safe_get(
                    creation_result,
                    "result_data.response.data.Data.Message",
                    "Заказ успешно создан",
                )
                await send_notification_workflow(
                    {
                        "to_emails": email,
                        "subject": "Заказ создан",
                        "message": message,
                    }
                )
            except Exception as exc:
                await handle_error(
                    "Ошибка отправки уведомления",
                    f"Ошибка при отправке уведомления о создании заказа: {exc}",
                )

        # Этап 2: Ожидание обработки заказа
        await managed_pause(delay_seconds=INITIAL_DELAY)

        # Этап 3: Получение результата обработки заказа
        getting_result = None

        for attempt in range(MAX_RESULT_ATTEMPTS + 1):
            try:
                getting_result = await get_skb_order_result_workflow(
                    order_data
                )

                if getting_result.get("success"):
                    if email:
                        await send_notification_task(
                            {
                                "to_emails": email,
                                "subject": "Заказ выполнен",
                                "message": f"Заказ {order_id} успешно обработан",
                            }
                        )
                    return getting_result

                if attempt < MAX_RESULT_ATTEMPTS:
                    await managed_pause(delay_seconds=RETRY_DELAY)

            except Exception as exc:
                await handle_error(
                    (
                        "Ошибка при получении результата"
                        if attempt < MAX_RESULT_ATTEMPTS
                        else "Финальная ошибка при получении результата"
                    ),
                    f"Попытка {attempt + 1}: {str(exc)}",
                )
                if attempt == MAX_RESULT_ATTEMPTS:
                    raise

        # Этап 4: Отправка результата
        # TO DO:заменить на воркфлоу
        sending_result = await send_order_result_task(order_data)

        if not sending_result.get("success"):
            await handle_error(
                "Ошибка отправки результата",
                sending_result.get("error_message", "Неизвестная ошибка"),
            )

        return sending_result

    except Exception as exc:
        await handle_error(
            "Критическая ошибка в процессе обработки",
            f"Неожиданная ошибка: {str(exc)}",
        )
        raise
