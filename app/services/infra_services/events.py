from logging import Logger
from typing import Any

from app.infra.clients.stream import redis_broker
from app.services.infra_services.mail import MailService, get_mail_service
from app.utils.logging_service import stream_logger


@redis_broker.subscriber(
    stream="email_events",
    retry=True,
)
async def handle_send_email(data: Any, logger: Logger = stream_logger):
    """
    Обрабатывает событие отправки email.

    Args:
        data (dict): Данные для отправки email.
    """
    try:
        mail_service: MailService = await get_mail_service()

        await mail_service.send_email(
            to_emails=data["to_emails"],
            subject=data["subject"],
            message=data["message"],
        )
    except Exception:
        logger.error("Failed to send email", exc_info=True)
        # Можно добавить логику повторной попытки
        await redis_broker.publish(data, stream="email_events", delay=60)
