from celery import chain

from app.celery.celery_config import celery_manager
from app.config.settings import settings
from app.infra.stream_manager import stream_client
from app.services.infra_services.mail import mail_service
from app.services.route_services.orders import OrderService, get_order_service
from app.utils.utils import utilities


__all__ = ("process_order_workflow",)


celery_app = celery_manager.app

# Инициализация сервиса заказов
order_service: OrderService = get_order_service()


@celery_app.task(
    name="send_mail",
    bind=True,
    max_retries=settings.celery.task_min_retries,
    default_retry_delay=settings.celery.task_default_retry_delay,
    retry_backoff=True,
    autoretry_for=(Exception,),
    ignore_result=False,
    queue=settings.celery.task_default_queue,
)
def send_email(self, data: dict):
    """
    Отправляет сообщение.

    Args:
        data (dict): Параметры отправки сообщения.
    """

    async def inner_send_mail(data):
        try:
            # Вызываем метод сервиса для отправки сообщения
            await mail_service.send_email(
                to_emails=data.get("to_emails"),
                subject=data.get("subject"),
                message=data.get("message"),
            )
        except Exception as exc:
            self.retry(exc=exc, throw=False)

    return utilities.execute_async_task(inner_send_mail())


@celery_app.task(
    name="send_result_to_gd",
    bind=True,
    max_retries=settings.celery.task_min_retries,
    default_retry_delay=settings.celery.task_default_retry_delay,
    retry_backoff=True,
    autoretry_for=(Exception,),
    ignore_result=False,
    queue=settings.celery.task_default_queue,
)
def send_result_to_gd(self, order_id: int):
    """
    Отправляет результат заказа в GD.

    Args:
        order_id (int): Идентификатор заказа.

    Returns:
        dict: Данные заказа, включая ссылки на файлы и результат.
    """

    async def inner_send_result_to_gd():
        try:
            # Вызываем метод сервиса для отправки результата в GD
            result = await order_service.send_data_to_gd(order_id=order_id)
            await stream_client.publish_event(
                event_type="order_send", data={"order": order_id}
            )
            return result
        except Exception as exc:
            self.retry(exc=exc, throw=False)

    return utilities.execute_async_task(inner_send_result_to_gd())


@celery_app.task(
    name="send_requests_for_get_result",
    bind=True,
    max_retries=settings.celery.task_min_retries,
    default_retry_delay=settings.celery.task_default_retry_delay,
    retry_backoff=True,
    autoretry_for=(Exception,),
    ignore_result=False,
    queue=settings.celery.task_default_queue,
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

    return utilities.execute_async_task(inner_send_requests_for_get_result())


@celery_app.task(
    name="send_requests_for_create_order",
    bind=True,
    max_retries=settings.celery.task_min_retries,
    default_retry_delay=settings.celery.task_default_retry_delay,
    autoretry_for=(Exception,),
    ignore_result=False,
    queue=settings.celery.task_default_queue,
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

    return utilities.execute_async_task(inner_send_requests_for_create_order())


@celery_app.task(
    name="process_order_workflow",
    bind=True,
    max_retries=settings.celery.task_min_retries,
    default_retry_delay=settings.celery.task_default_retry_delay,
    autoretry_for=(Exception,),
    ignore_result=False,
    queue=settings.celery.task_default_queue,
)
def process_order_workflow(self, order_id: int):
    """
    Управляет цепочкой задач для обработки заказа.

    Args:
        order_id (int): Идентификатор заказа.
    """
    try:
        # Создаем цепочку задач
        workflow = chain(
            send_requests_for_create_order.s(order_id),
            send_requests_for_get_result.s(order_id).set(countdown=1800),
            send_result_to_gd.s(order_id),
        )
        workflow.apply_async()  # Запускаем цепочку задач
    except Exception as exc:
        self.retry(exc=exc, throw=False)
