from typing import Any, Dict

from prefect import flow

from app.background_tasks.tasks import (
    create_skb_order_task,
    get_skb_order_result_task,
    send_notification_task,
    send_order_result_task,
)
from app.background_tasks.utils import handle_error, managed_pause
from app.config.constants import consts
from app.config.settings import settings
from app.utils.errors import ServiceError
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
    cad_num: str,
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
                "subject": f"Статус {action} заказа {order_id} по объекту {cad_num}",
                "message": f"Заказ {order_id}: {message}",
            }
        )
    except Exception as exc:
        error_msg = f"Ошибка отправки уведомления о {action}: {exc}"
        await _handle_order_error(email, order_id, cad_num, action, error_msg)
        raise


async def _handle_order_error(
    email: str, order_id: str, cad_num: str, action: str, error: str
) -> None:
    """Обрабатывает ошибки связанные с заказом."""
    await handle_error(
        email=email,
        ident_data=f"Заказ {order_id} по объекту {cad_num}",
        subject=f"Ошибка {action} заказа по объекту {cad_num}",
        error=error,
    )
    tasks_logger.error(
        f"Ошибка {action} заказа {order_id} по объекту {cad_num}: {error}"
    )


@flow(
    name="send-notification-workflow",
    description="Отправляет письмо клиенту по указанному адресу электронной почты",
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

        print(f"body: {body}")
    except Exception as exc:
        tasks_logger.error(f"Error during sending mail: {str(exc)}")


@flow(
    name="create-skb-order-workflow",
    description="Создает новый заказ в системе SKB для клиента с указанным номером заказа",
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
    cad_num = order_data.get("pledge_cadastral_number")

    try:
        result = await create_skb_order_task(order_data)  # type: ignore

        print(f"result: {result}")

        if not result:
            await _handle_order_error(
                email, order_id, cad_num, "создания", "Заказ не создан"
            )
            raise ServiceError

        await _send_status_notification(
            email,
            order_id,
            "создания",
            cad_num,
            result,
            "Заказ успешно создан",
            "result_data.response.data.Data.Message",
        )
        return result
    except Exception as exc:
        tasks_logger.error(
            f"Ошибка процесса создания заказа {order_id}: {exc}"
        )
        raise


@flow(
    name="get-skb-order-result-workflow",
    description="Отправляет результат обработки заказа в системе SKB в очередь для чтения",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    log_prints=True,
)
async def get_skb_order_result_workflow(order_data: dict) -> Dict[str, Any]:
    """
    Отправляет результат SKB с задержкой при повторах в очередь для чтения.

    Args:
        body (dict): Данные заказа.

    Returns:
        Dict[str, Any]: Результат отправки.
    """
    order_id = order_data.get("id", "UNKNOWN")
    email = order_data.get("email_for_answer")
    cad_num = order_data.get("pledge_cadastral_number")

    try:
        for _ in range(consts.MAX_RESULT_ATTEMPTS + 1):
            result = await get_skb_order_result_task(order_data)  # type: ignore

            print(f"result: {result}")

            if not result:
                await _handle_order_error(
                    email,
                    order_id,
                    cad_num,
                    "обработки",
                    "Результат не обработан",
                )

                await managed_pause(delay_seconds=consts.RETRY_DELAY)
        return result
    except Exception as exc:
        tasks_logger.error(
            f"Ошибка процесса обработки заказа {order_id}: {exc}"
        )
        raise


@flow(
    name="send-skb-order-result-task-workflow",
    description="Отправляет результат обработки заказа в системе SKB",
    log_prints=True,
)
async def send_skb_order_result_workflow(order_data: dict) -> Dict[str, Any]:
    """
    Отправляет результат обработки заказа в системе SKB с экспоненциальной задержкой при повторах.

    Args:
        body (dict): Данные заказа.

    Returns:
        Dict[str, Any]: Результат обработки заказа.
    """
    order_id = order_data.get("id", "UNKNOWN")
    email = order_data.get("email_for_answer")
    cad_num = order_data.get("pledge_cadastral_number")

    try:
        result = await send_order_result_task(order_data)  # type: ignore

        print(f"result: {result}")

        if not result:
            error_msg = result.get(
                "error_message", "Неизвестная ошибка отправки"
            )
            await _handle_order_error(
                email, order_id, cad_num, "отправки", error_msg
            )
            raise ServiceError(error_msg)
        return result
    except Exception as exc:
        tasks_logger.error(
            f"Ошибка процесса отправки результата заказа {order_id}: {exc}"
        )
        raise


@flow(
    name="order-processing-workflow",
    description="Оптимизированный процесс обработки заказов с улучшенной обработкой ошибок",
    log_prints=True,
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
        creating_result = await create_skb_order_workflow(order_data)
        print(f"creating_result: {creating_result}")

        # Этап 2: Ожидание обработки заказа
        await managed_pause(delay_seconds=consts.INITIAL_DELAY)
        print(f"unpaused by: {consts.INITIAL_DELAY} seconds")

        # Этап 3: Получение результата обработки заказа
        gettting_result = await get_skb_order_result_workflow(order_data)
        print(f"gettting_result: {gettting_result}")

        # Этап 4: Отправка результата
        sending_result = await send_skb_order_result_workflow(order_data)
        print(f"sending_result: {sending_result}")
    except Exception as exc:
        tasks_logger.error(f"Ошибка order_processing_workflow: {exc}")
        await handle_error(
            email=order_data.get("email_for_answer"),
            ident_data=f"Заказ {order_data.get("id", "UNKNOWN")}",
            subject="Критическая ошибка в процессе обработки",
            error=f"Неожиданная ошибка: {str(exc)}",
        )
        raise
