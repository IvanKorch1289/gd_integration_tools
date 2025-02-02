from typing import Callable, Dict

from app.infra.event_bus import event_client
from app.utils.logging import app_logger


__all__ = "event_router"


class EventRouter:
    def __init__(self):
        self.handlers: Dict[str, Callable] = {}
        self._register_handlers()

        # Регистрируем все обработчики в event_client
        for event_type, handler in self.handlers.items():
            event_client.register_handler(event_type, handler)

    def _register_handlers(self):
        """Регистрация всех обработчиков событий"""
        self._add_handler("order_created", self.handle_order_created)
        self._add_handler("init_mail_send", self.handle_init_mail_send)

    def _add_handler(self, event_type: str, handler: Callable):
        self.handlers[event_type] = handler
        app_logger.debug(f"Registered handler for {event_type}")

    async def handle_order_created(self, data: dict):
        app_logger.info(f"Handling order created: {data}")

        # Отправка события в другую систему
        from app.celery.tasks import process_order_workflow

        process_order_workflow.apply_async(
            args=[data.get("order_id")], queue="high_priority", retry=True
        )

    async def handle_init_mail_send(self, data: dict):
        app_logger.info(f"Handling initialize mail sending: {data}")

        # Отправка события в другую систему
        from app.celery.tasks import send_email

        send_email.apply_async(args=[data], queue="high_priority", retry=True)


event_router = EventRouter()
