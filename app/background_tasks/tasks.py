from prefect import task

from app.background_tasks.dicts import ProcessingResult
from app.config.settings import settings
from app.services.route_services.orders import get_order_service
from app.utils.logging_service import tasks_logger


__all__ = (
    "send_notification_task",
    "create_skb_order_task",
    "get_skb_order_result_task",
    "send_order_result_task",
)


@task(
    name="send-notification",
    description="Отправляет электронное письмо по указанному адресу",
    retries=settings.tasks.task_max_attempts,
    retry_delay_seconds=settings.tasks.task_seconds_delay,
    retry_jitter_factor=settings.tasks.task_retry_jitter_factor,
    timeout_seconds=30,
    persist_result=True,
)
async def send_notification_task(body: dict) -> dict:
    """
    Отправляет электронное письмо с использованием сервиса почты.

    Args:
        body (dict): Данные для отправки письма, включая:
            - to_emails (list): Список адресов получателей.
            - subject (str): Тема письма.
            - message (str): Текст сообщения.

    Returns:
        dict: Результат отправки письма.

    Raises:
        Exception: В случае ошибки при отправке письма.
    """
    from app.services.infra_services.mail import get_mail_service

    async with get_mail_service() as mail_service:
        return await mail_service.send_email(
            to_emails=body["to_emails"],
            subject=body["subject"],
            message=body["message"],
        )


@task(
    name="create-skb-order",
    description="Создает заказ в системе SKB с логикой повторных попыток",
    retries=settings.tasks.task_max_attempts,
    retry_delay_seconds=settings.tasks.task_seconds_delay,
    retry_jitter_factor=settings.tasks.task_retry_jitter_factor,
    timeout_seconds=3600,
    persist_result=True,
)
async def create_skb_order_task(order_data: dict) -> ProcessingResult:
    """
    Создает новый заказ в системе SKB с валидацией и повторными попытками.

    Args:
        order_data (dict): Данные заказа, включая:
            - id (str): Идентификатор заказа.

    Returns:
        ProcessingResult: Результат обработки с полями:
            - success (bool): Успешность операции.
            - order_id (str): Идентификатор заказа.
            - result_data (dict): Данные результата.
            - error_message (str): Сообщение об ошибке.

    Raises:
        ValueError: Если отсутствует обязательный параметр order_id.
        Exception: В случае ошибки при создании заказа.
    """
    if not order_data.get("id"):
        raise ValueError("Отсутствует обязательный параметр order_id")

    try:
        result = await get_order_service().create_skb_order(
            order_id=order_data["id"]
        )

        if result.get("response", {}).get("status_code", {}) != 200:
            raise Exception("Ошибка создания заказа в системе SKB")

        response = {
            "success": True,
            "order_id": order_data["id"],
            "result_data": result,
            "error_message": None,
        }
        tasks_logger.info(f"Заказ создан: {response}")
        return response
    except Exception as exc:
        tasks_logger.error(
            f"Ошибка создания заказа: {str(exc)}", exc_info=True
        )
        return {
            "success": False,
            "order_id": order_data["id"],
            "result_data": {},
            "error_message": str(exc),
        }


@task(
    name="get-skb-order-result",
    description="Получает результат заказа в системе SKB с логикой повторных попыток",
    retries=settings.tasks.task_max_attempts,
    retry_delay_seconds=settings.tasks.task_seconds_delay,
    retry_jitter_factor=settings.tasks.task_retry_jitter_factor,
    timeout_seconds=86400,
    persist_result=True,
)
async def get_skb_order_result_task(order_data: dict) -> ProcessingResult:
    """
    Получает результат заказа в системе SKB с валидацией и повторными попытками.

    Args:
        order_data (dict): Данные заказа, включая:
            - id (str): Идентификатор заказа.

    Returns:
        ProcessingResult: Результат обработки с полями:
            - success (bool): Успешность операции.
            - order_id (str): Идентификатор заказа.
            - result_data (dict): Данные результата.
            - error_message (str): Сообщение об ошибке.

    Raises:
        ValueError: Если отсутствует обязательный параметр order_id.
        Exception: В случае ошибки при получении результата.
    """
    if not order_data.get("order_id"):
        raise ValueError("Отсутствует обязательный параметр order_id")

    try:
        result = await get_order_service().get_order_file_and_json_from_skb(
            order_id=order_data["order_id"]
        )

        if result.get("response", {}).get("status_code", {}) != 200:
            raise Exception("Ошибка получения результата заказа в системе SKB")

        return {
            "success": True,
            "order_id": order_data["order_id"],
            "result_data": result,
            "error_message": None,
        }
    except Exception as exc:
        tasks_logger.error(
            f"Ошибка получения результата: {str(exc)}", exc_info=True
        )
        return {
            "success": False,
            "order_id": order_data["id"],
            "result_data": {},
            "error_message": str(exc),
        }


@task(
    name="send-order-result",
    description="Отправляет результат заказа во внешнюю систему с логикой повторных попыток",
    retries=settings.tasks.task_max_attempts,
    retry_delay_seconds=settings.tasks.task_seconds_delay,
    retry_jitter_factor=settings.tasks.task_retry_jitter_factor,
    timeout_seconds=3600,
    persist_result=True,
)
async def send_order_result_task(order_data: dict) -> ProcessingResult:
    """
    Отправляет результат заказа во внешнюю систему с валидацией и повторными попытками.

    Args:
        order_data (dict): Данные заказа, включая:
            - id (str): Идентификатор заказа.

    Returns:
        ProcessingResult: Результат обработки с полями:
            - success (bool): Успешность операции.
            - order_id (str): Идентификатор заказа.
            - result_data (dict): Данные результата.
            - error_message (str): Сообщение об ошибке.

    Raises:
        ValueError: Если отсутствует обязательный параметр order_id.
        Exception: В случае ошибки при отправке результата.
    """
    if not order_data.get("id"):
        raise ValueError("Отсутствует обязательный параметр order_id")

    try:
        result = await get_order_service().send_order_data(
            order_id=order_data["id"]
        )

        return {
            "success": True,
            "order_id": order_data["id"],
            "result_data": result,
            "error_message": None,
        }
    except Exception as exc:
        tasks_logger.error(
            f"Ошибка отправки результата: {str(exc)}", exc_info=True
        )
        return {
            "success": False,
            "order_id": order_data["id"],
            "result_data": {},
            "error_message": str(exc),
        }
