import asyncio
import json_tricks
from celery import Celery, chain
from fastapi.responses import JSONResponse

from app.core.settings import settings
from app.orders.service import OrderService, get_order_service


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
order_service: OrderService = get_order_service()


def run_async_task(task):
    """
    Запускает асинхронную задачу в синхронном контексте.

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
    """
    Отправляет результат заказа в GD (Государственный Депозитарий).

    Args:
        order_id (int): Идентификатор заказа.

    Returns:
        dict: Данные заказа, включая ссылки на файлы и результат.
    """

    async def inner_send_result_to_gd():
        try:
            # Вызываем метод сервиса для отправки результата в GD
            result = await order_service.send_data_to_gd(order_id=order_id)
            return result
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
def send_requests_for_get_result(self, order_id: int):
    """
    Отправляет запросы для получения результата заказа.

    Args:
        order_id (int): Идентификатор заказа.

    Returns:
        str: Результат выполнения запроса.
    """

    async def inner_send_requests_for_get_result():
        try:
            # Вызываем метод сервиса для получения результата
            result = await order_service.get_order_file_and_json_from_skb(
                order_id=order_id
            )

            # Проверяем, готов ли результат
            if result is None or result.get("hasError", True):
                # Если результат не готов, вызываем исключение для повторного выполнения задачи
                raise ValueError("Результат еще не готов")

            return result
        except Exception as exc:
            # Повторяем задачу, если результат не готов или произошла ошибка
            self.retry(exc=exc, throw=False)

    return run_async_task(inner_send_requests_for_get_result())


@celery_app.task(
    name="send_requests_for_create_order",
    bind=True,
    max_retries=settings.bts_settings.bts_min_retries,
    default_retry_delay=settings.bts_settings.bts_min_retry_delay,
    retry_backoff=True,
)
def send_requests_for_create_order(self, order_id: int):
    """
    Отправляет запросы для создания заказа.

    Args:
        order_id (int): Идентификатор заказа.

    Returns:
        str: Результат выполнения запроса.
    """

    async def inner_send_requests_for_create_order():
        try:
            # Вызываем метод сервиса для создания заказа
            return await order_service.create_skb_order(order_id=order_id)
        except Exception as exc:
            self.retry(exc=exc, throw=False)

    return run_async_task(inner_send_requests_for_create_order())


@celery_app.task(
    name="process_order_workflow",
    bind=True,
    max_retries=settings.bts_settings.bts_min_retries,
    default_retry_delay=settings.bts_settings.bts_min_retry_delay,
    retry_backoff=True,
)
def process_order_workflow(self, order_id: int, email: str):
    """
    Управляет цепочкой задач для обработки заказа.

    Args:
        order_id (int): Идентификатор заказа.
        email (str): Адрес электронной почты для уведомлений.
    """
    try:
        # Создаем цепочку задач
        workflow = chain(
            send_requests_for_create_order.s(order_id),
            send_requests_for_get_result.s(order_id).set(
                countdown=settings.bts_settings.bts_expiration_time
            ),
            send_result_to_gd.s(order_id),
        )
        workflow.apply_async()  # Запускаем цепочку задач
    except Exception as exc:
        self.retry(exc=exc, throw=False)
