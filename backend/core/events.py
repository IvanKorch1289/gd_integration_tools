from logging import Logger
from typing import Callable, Dict, List

from pydantic import BaseModel

from backend.core.logging_config import app_logger
from backend.core.utils import utilities


# Модель для события
class Event(BaseModel):
    event_type: str
    payload: dict


# Шина событий
class EventBus:
    def __init__(self, logger: Logger):
        # Логгер для записи событий
        self.logger = logger
        # Словарь для хранения обработчиков событий
        self._handlers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, handler: Callable):
        """
        Подписывает обработчик на определённый тип события.
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        self.logger.info(f"Обработчик подписан на событие: {event_type}")

    def unsubscribe(self, event_type: str, handler: Callable):
        """
        Отписывает обработчик от определённого типа события.
        """
        if event_type in self._handlers:
            self._handlers[event_type].remove(handler)
            self.logger.info(f"Обработчик отписан от события: {event_type}")

    async def emit(self, event: Event):
        """
        Отправляет событие в шину и вызывает все подписанные обработчики.
        """
        self.logger.info(
            f"Событие получено: {event.event_type}, payload: {event.payload}"
        )
        if event.event_type in self._handlers:
            for handler in self._handlers[event.event_type]:
                try:
                    # Вызываем обработчики асинхронно
                    await handler(event.payload)
                    self.logger.info(
                        f"Обработчик для события {event.event_type} выполнен успешно."
                    )
                except Exception as e:
                    self.logger.error(
                        f"Ошибка в обработчике для события {event.event_type}: {str(e)}",
                        exc_info=True,
                    )


event_bus = EventBus(logger=app_logger)


# Обработчик события "order_created"
async def on_order_created(payload: dict):
    app_logger.info(f"Обработка события 'order_created': {payload}")

    from core.background_tasks import celery_app

    await utilities.send_email(
        to_email=payload["email"],
        subject="Новый заказ создан",
        message=f"Новый заказ создан с ID: {payload['order_id']}",
    )
    celery_app.send_task("send_requests_for_create_order", args=[payload["order_id"]])


# Обработчик события "order_sending_skb"
async def on_order_sending_skb(payload: dict):
    app_logger.info(f"Обработка события 'on_order_sending_skb': {payload}")

    await utilities.send_email(
        to_email=payload["email"],
        subject="Новый заказ зарегистрирован в СКБ-Техно",
        message=f"Новый заказ зарегистрирован в СКБ-Техно: {payload['order_id']}",
    )


# Подписываем обработчик на события
event_bus.subscribe("order_created", on_order_created)
event_bus.subscribe("order_sending_skb", on_order_sending_skb)
