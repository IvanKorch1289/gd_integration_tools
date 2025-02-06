from typing import Callable

from app.infra.stream_manager import StreamClient, stream_client
from app.utils.logging_service import app_logger


__all__ = (
    "event_service",
    "EventService",
)


class EventService:
    """Router for registering event handlers and business logic.

    Responsibilities:
    - Central place для регистрации обработчиков событий
    - Содержит бизнес-логику обработки конкретных событий
    - Интегрируется с другими компонентами системы
    """

    def __init__(self, event_client: StreamClient):
        self.event_client = event_client
        self.logger = app_logger

    async def register_handlers(self) -> None:
        """Register all event handlers during initialization"""
        await self._add_handler("order_created", self.handle_order_created)
        await self._add_handler("init_mail_send", self.handle_init_mail_send)

    async def _add_handler(self, event_type: str, handler: Callable) -> None:
        """Helper method for handler registration"""
        await self.event_client.register_handler(event_type, handler)
        self.logger.debug(f"Registered handler for {event_type}")

    async def handle_order_created(self, data: dict):
        self.logger.info(f"Handling order created: {data}")

        # Отправка события в другую систему
        from app.celery.tasks import process_order_workflow

        try:
            process_order_workflow.apply_async(
                args=[data.get("order_id")], queue="high_priority", retry=True
            )
        except Exception:
            self.logger.error("Error processing order created", exc_info=True)

    async def handle_init_mail_send(self, data: dict):
        self.logger.info(f"Handling initialize mail sending: {data}")

        # Отправка события в другую систему
        from app.celery.tasks import send_email

        try:
            send_email.apply_async(
                args=[data], queue="high_priority", retry=True
            )
        except Exception:
            self.logger.error(
                "Error processing initialize mail sending", exc_info=True
            )


event_service = EventService(event_client=stream_client)
