import traceback

import asyncio
from celery import Celery
from fastapi import status

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
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        order: Order = loop.run_until_complete(order_service.get(order_id=order_id))
        file_links = loop.run_until_complete(
            order_service.get_order_file_link(order_id=order_id)
        )
        data = {
            "order": order.object_uuid,
            "result": order.response_data,
            "file_links": file_links,
        }
        return data
    except Exception as exc:
        self.retry(exc=str(exc))
    finally:
        loop.close()


@celery_app.task(
    name="send_requests_for_get_result",
    bind=True,
    max_retries=settings.bts_settings.bts_max_retries,
    default_retry_delay=settings.bts_settings.bts_max_retry_delay,
    retry_backoff=True,
)
def send_requests_for_get_result(self, order_id):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(
            order_service.get_order_file_and_json(order_id=order_id)
        )
        if not result:
            error_message = {
                "hasError": False,
                "message": "The response to the query is not ready yet",
            }
            raise ValueError(error_message)

        send_result_to_gd.delay(order_id)
        return
    except Exception as exc:
        self.retry(exc=str(exc))
    finally:
        loop.close()


@celery_app.task(
    name="send_requests_for_create_order",
    bind=True,
    max_retries=settings.bts_settings.bts_min_retries,
    default_retry_delay=settings.bts_settings.bts_min_retry_delay,
    retry_backoff=True,
)
def send_requests_for_create_order(self, order_id):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(
            order_service.create_skb_order(order_id=order_id)
        )
        if result.status_code == status.HTTP_200_OK:
            loop.run_until_complete(
                order_service.update(order_id=order_id, data={"is_send_to_skb": True})
            )
    except Exception:
        self.retry(traceback.format_exc())
    finally:
        loop.close()
