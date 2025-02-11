from datetime import timedelta
from logging import Logger
from typing import Any

from app.infra.clients.stream import stream_client
from app.utils.logging_service import stream_logger


@stream_client.redis_broker.subscriber(
    stream="email_send_stream",
    retry=True,
)
async def handle_send_email(data: Any, logger: Logger = stream_logger):
    """
    Обрабатывает событие отправки email.

    Args:
        data (dict): Данные для отправки email.
    """
    try:
        from app.services.infra_services.mail import get_mail_service

        mail_service = get_mail_service()
        await mail_service.send_email(
            to_emails=data["to_emails"],
            subject=data["subject"],
            message=data["message"],
        )
    except Exception:
        logger.error("Failed to send email", exc_info=True)
        await stream_client.publish_to_redis(
            message=data, stream="email_events", delay=timedelta(seconds=60)
        )


@stream_client.redis_broker.subscriber(
    stream="order_send_to_skb_stream",
    retry=True,
    no_ack=False,
)
async def handle_order_send_to_skb(data: Any, logger: Logger = stream_logger):
    """
    Обрабатывает событие отправки email.

    Args:
        data (dict): Данные для отправки email.
    """
    try:
        from app.services.route_services.orders import get_order_service

        service = get_order_service()

        await service.create_skb_order(order_id=data)  # type: ignore
    except Exception:
        logger.error("Failed to send email", exc_info=True)
        await stream_client.publish_to_redis(
            message=data, stream="email_events", delay=timedelta(seconds=60)
        )
