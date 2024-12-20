import asyncio
from celery import Celery
from celery.schedules import crontab

from backend.api_skb.enums import ResponseTypeChoices
from backend.core.settings import settings
from backend.orders.filters import OrderFilter
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
    beat_schedule={
        "every-thirty-minutes-task": {
            "task": "send_responces_to_skb_by_orders",
            "schedule": crontab(minute="*/30", hour="6-21"),
        },
    },
)

order_service = OrderService()


def sync_get_order_result(
    order_id: int, response_type: str, order_service: OrderService = order_service
):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(
        order_service.get_order_result(order_id, response_type)
    )
    return result


@celery_app.task(name="send_responces_to_skb_by_orders")
def send_responces_to_skb_by_orders(order_service: OrderService = order_service):
    filter = OrderFilter.model_validate(
        {"is_active": True, "is_send_request_to_skb": True}
    )
    orders = order_service.get_by_params(filter=filter)
    for order in orders:
        sync_get_order_result(
            order_service=order_service,
            order_id=order.id,
            response_type=ResponseTypeChoices.pdf,
        )
        sync_get_order_result(
            order_service=order_service,
            order_id=order.id,
            response_type=ResponseTypeChoices.json,
        )
        if order.response_date and order.files:
            order_service.update(key="id", value=order.id, data={"is_active": False})
