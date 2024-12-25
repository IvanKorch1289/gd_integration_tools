from celery import Celery
from settings import settings

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


def order_service_dependency():
    return OrderService()
