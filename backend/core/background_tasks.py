import asyncio
import json_tricks
from celery import Celery
from fastapi.responses import JSONResponse

from backend.core.settings import settings
from backend.core.utils import utilities
from backend.orders.models import Order
from backend.orders.service import OrderService


# Настройка подключения к Redis
redis_url = (
    f"{settings.redis_settings.redis_url}/{settings.redis_settings.redis_db_queue}"
)

# Инициализация Celery
celery_app = Celery("tasks", broker=redis_url, backend=redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    enable_utc=True,
    timezone="Europe/Moscow",
    broker_connection_retry_on_startup=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# Инициализация сервиса заказов
order_service = OrderService()


def run_async_task(task):
    """Запускает асинхронную задачу в синхронном контексте.

    Args:
        task: Асинхронная задача для выполнения.

    Returns:
        Результат выполнения задачи.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(task)
        if isinstance(result, JSONResponse):
            result = result.body.decode("utf-8")
        else:
            result = json_tricks.dumps(result).encode("utf-8")
        return result
    finally:
        if loop.is_closed():
            loop.close()


@celery_app.task(
    name="send_result_to_gd",
    bind=True,
    max_retries=settings.bts_settings.bts_max_retries,
    default_retry_delay=settings.bts_settings.bts_max_retry_delay,
    retry_backoff=True,
)
def send_result_to_gd(self, order_id: int):
    """Отправляет результат заказа в GD (Государственный Депозитарий).

    Args:
        order_id (int): Идентификатор заказа.

    Returns:
        dict: Данные заказа, включая ссылки на файлы и результат.
    """

    async def inner_send_result_to_gd():
        try:
            order: Order = await order_service.get(key="id", value=order_id)
            file_links = await order_service.get_order_file_link(order_id=order_id)

            data = {
                "order": order.object_uuid,
                "result": order.response_data,
                "file_links": file_links,
            }

            return data
        except Exception as exc:
            self.retry(exc=exc, throw=False)

    return run_async_task(inner_send_result_to_gd())


@celery_app.task(
    name="send_requests_for_get_result",
    bind=True,
    max_retries=settings.bts_settings.bts_max_retries,
    default_retry_delay=settings.bts_settings.bts_max_retry_delay,
    retry_backoff=True,
)
def send_requests_for_get_result(self, order_id):
    """Отправляет запросы для получения результата заказа.

    Args:
        order_id (int): Идентификатор заказа.

    Returns:
        str: Результат выполнения запроса.
    """

    async def inner_send_requests_for_get_result():
        try:
            result = await order_service.get_order_file_and_json_from_skb(
                order_id=order_id
            )

            if not result:
                error_message = {
                    "hasError": False,
                    "message": "The response to the query is not ready yet",
                }
                raise ValueError(error_message)

            celery_app.send_task("send_result_to_gd", args=[order_id])

            order: Order = await order_service.get(key="id", value=order_id)

            await utilities.send_email(
                to_email=order.email_for_send,
                subject=f"Получен результат заказа выписки по заказу {order.email_for_answer}",
                message=f"Получен результат заказа выписки по объекту id = {order.email_for_answer}",
            )

            return str(result)
        except Exception as exc:
            self.retry(exc=exc, throw=False)

    return run_async_task(inner_send_requests_for_get_result())


@celery_app.task(
    name="send_requests_for_create_order",
    bind=True,
    max_retries=settings.bts_settings.bts_min_retries,
    default_retry_delay=settings.bts_settings.bts_min_retry_delay,
    retry_backoff=True,
)
def send_requests_for_create_order(self, order_id):
    """Отправляет запросы для создания заказа.

    Args:
        order_id (int): Идентификатор заказа.

    Returns:
        str: Результат выполнения запроса.
    """

    async def inner_send_requests_for_create_order():
        try:
            result = await order_service.create_skb_order(order_id=order_id)

            celery_app.send_task(
                "send_requests_for_get_result",
                args=[order_id],
                countdown=settings.bts_settings.bts_expiration_time,
            )

            return result
        except Exception as exc:
            self.retry(exc=exc, throw=False)

    return run_async_task(inner_send_requests_for_create_order())
