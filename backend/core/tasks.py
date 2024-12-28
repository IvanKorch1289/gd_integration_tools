import asyncio
from celery import Celery

from backend.core.settings import settings
from backend.orders.models import Order
from backend.orders.service import OrderService


redis_url = f"redis://{settings.redis_settings.redis_host}:{settings.redis_settings.redis_port}/{settings.redis_settings.redis_db_queue}"


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


order_service = OrderService()


@celery_app.task(
    name="send_result_to_gd",
    bind=True,
    max_retries=settings.bts_settings.bts_max_retries,
    default_retry_delay=settings.bts_settings.bts_max_retry_delay,
    retry_backoff=True,
)
def send_result_to_gd(self, order_id: int):
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
            self.retry(exc=(exc, order_id), throw=False)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(inner_send_result_to_gd())
    finally:
        if loop.is_closed():
            loop.close()


@celery_app.task(
    name="send_requests_for_get_result",
    bind=True,
    max_retries=settings.bts_settings.bts_max_retries,
    default_retry_delay=settings.bts_settings.bts_max_retry_delay,
    retry_backoff=True,
)
def send_requests_for_get_result(self, order_id):
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
        except Exception as exc:
            self.retry(exc=(exc, order_id), throw=False)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(inner_send_requests_for_get_result())
    finally:
        if loop.is_closed():
            loop.close()


@celery_app.task(
    name="send_requests_for_create_order",
    bind=True,
    max_retries=settings.bts_settings.bts_min_retries,
    default_retry_delay=settings.bts_settings.bts_min_retry_delay,
    retry_backoff=True,
)
def send_requests_for_create_order(self, order_id):
    async def inner_send_requests_for_create_order():
        try:
            await order_service.create_skb_order(order_id=order_id)

            celery_app.send_task(
                "send_requests_for_get_result",
                args=[order_id],
                countdown=settings.bts_settings.bts_expiration_time,
            )
        except Exception as exc:
            self.retry(exc=(exc, order_id), throw=False)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(inner_send_requests_for_create_order())
    finally:
        if loop.is_closed():
            loop.close()
