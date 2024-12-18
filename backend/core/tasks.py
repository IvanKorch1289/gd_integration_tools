import asyncio
from celery import Celery
from celery.schedules import crontab

from backend.api_skb.enums import ResponseTypeChoices
from backend.core.settings import settings
from backend.orders.filters import OrderFilter
from backend.orders.service import OrderService


redis_url = f"{settings.redis_settings.redis_host}:{settings.redis_settings.redis_port}"


app = Celery(
    "tasks", broker=f"redis://{redis_url}/{settings.redis_settings.redis_db_queue}"
)


CELERY_BEAT_SCHEDULE = {
    "add-every-30-minutes": {
        "task": "tasks.add",
        "schedule": crontab(minute="*/30"),
        "args": (16, 16),
    },
}


service = OrderService()


def sync_get_order_result(order_id: int, response_type: str):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(service.get_order_result(order_id, response_type))
    return result


@app.task
def send_responces_to_skb_by_orders():
    filter = OrderFilter.model_validate({"is_active": True})
    orders = service.get_by_params(filter=filter)
    for order in orders:
        sync_get_order_result(order_id=order.id, response_type=ResponseTypeChoices.pdf)
        sync_get_order_result(order_id=order.id, response_type=ResponseTypeChoices.json)
