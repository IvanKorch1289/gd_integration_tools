from logging import Logger
from typing import Callable, Dict, List

from pydantic import BaseModel

from app.utils import app_logger, mail_service, singleton, utilities


__all__ = (
    "Event",
    "event_bus",
)


class Event(BaseModel):
    """
    Модель для представления события.

    Атрибуты:
        event_type (str): Тип события.
        payload (dict): Данные, связанные с событием.
    """

    event_type: str
    payload: dict


@singleton
class EventBus:
    """
    Шина событий для управления подписками и обработкой событий.

    Атрибуты:
        logger (Logger): Логгер для записи событий.
        _handlers (Dict[str, List[Callable]]): Словарь для хранения обработчиков событий.
    """

    def __init__(self, logger: Logger):
        """
        Инициализирует шину событий.

        Args:
            logger (Logger): Логгер для записи событий.
        """
        self.logger = logger
        self._handlers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, handler: Callable):
        """
        Подписывает обработчик на определённый тип события.

        Args:
            event_type (str): Тип события.
            handler (Callable): Функция-обработчик события.
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        self.logger.info(f"Обработчик подписан на событие: {event_type}")

    def unsubscribe(self, event_type: str, handler: Callable):
        """
        Отписывает обработчик от определённого типа события.

        Args:
            event_type (str): Тип события.
            handler (Callable): Функция-обработчик события.
        """
        if event_type in self._handlers:
            self._handlers[event_type].remove(handler)
            self.logger.info(f"Обработчик отписан от события: {event_type}")

    async def emit(self, event: Event):
        """
        Отправляет событие в шину и вызывает все подписанные обработчики.

        Args:
            event (Event): Событие, которое нужно обработать.
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


# Инициализация шины событий
event_bus = EventBus(logger=app_logger)


async def on_order_created(payload: dict):
    """
    Обработчик события "order_created".

    Отправляет email и запускает цепочку задач для обработки заказа.

    Args:
        payload (dict): Данные, связанные с событием.
    """
    app_logger.info(f"Обработка события 'order_created': {payload}")

    # Отправляем email через обработчик on_email_send
    await on_email_send(
        {
            "email": payload["email"],
            "subject": "Новый заказ создан",
            "message": f"Новый заказ создан с ID: {payload['order_id']}",
        }
    )

    # Запускаем workflow обработки заказа
    from app.config.background_tasks import celery_app

    celery_app.send_task(
        "process_order_workflow",
        args=[payload["order_id"], payload["email"]],
    )


async def on_order_sending_skb(payload: dict):
    """
    Обработчик события "order_sending_skb".

    Отправляет email о регистрации заказа в СКБ-Техно.

    Args:
        payload (dict): Данные, связанные с событием.
    """
    app_logger.info(f"Обработка события 'on_order_sending_skb': {payload}")

    # Отправляем email через обработчик on_email_send
    await on_email_send(
        {
            "email": payload["email"],
            "subject": "Новый заказ зарегистрирован в СКБ-Техно",
            "message": f"Новый заказ зарегистрирован в СКБ-Техно: {payload['order_id']}",
        }
    )


async def on_email_send(payload: dict):
    """
    Обработчик события "email_send".

    Отправляет email на основе данных, переданных в payload.

    Args:
        payload (dict): Данные, связанные с событием.
    """
    app_logger.info(f"Обработка события 'email_send': {payload}")

    await mail_service.send_email(
        to_email=payload["email"],
        subject=payload["subject"],
        message=payload["message"],
    )


# Подписываем обработчики на события
event_bus.subscribe("order_created", on_order_created)
event_bus.subscribe("order_sending_skb", on_order_sending_skb)
event_bus.subscribe("email_send", on_email_send)
