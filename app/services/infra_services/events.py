from datetime import timedelta
from logging import Logger
from typing import Any

from faststream import Context

from app.config.constants import (
    MAX_ATTEMPTS_GET_ORDER_RESULT_FROM_SKB,
    MAX_ATTEMPTS_SEND_ORDER_TO_SKB,
)
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
async def handle_order_send_to_skb(
    data: Any,
    attempt: int = Context("message.headers.attempt", default=0),
    logger: Logger = stream_logger,
):
    """
    Обрабатывает событие отправки email.

    Args:
        data (dict): Данные для отправки email.
    """
    MAX_ATTEMPTS = MAX_ATTEMPTS_SEND_ORDER_TO_SKB

    try:
        from app.services.route_services.orders import get_order_service

        service = get_order_service()

        result = await service.create_skb_order(order_id=data)  # type: ignore

        if result.get("data").get("Result"):
            await stream_client.publish_to_redis(
                message={"data": data},
                stream="order_get_result_from_skb_stream",
                delay=timedelta(minutes=30),
            )
    except Exception:
        logger.error("Failed to send order to SKB", exc_info=True)
        if attempt >= MAX_ATTEMPTS:
            logger.error("Max retries reached")
            return
        await stream_client.publish_to_redis(
            message=data,
            stream="order_send_to_skb_stream",
            headers={"attempt": attempt + 1},
            delay=timedelta(minutes=5),
        )


@stream_client.redis_broker.subscriber(
    stream="order_get_result_from_skb",
    retry=True,
    no_ack=False,
)
async def handle_order_get_result_from_skb(
    data: Any,
    attempt: int = Context("message.headers.attempt", default=0),
    logger: Logger = stream_logger,
):
    """
    Обрабатывает событие отправки email.

    Args:
        data (dict): Данные для отправки email.
    """
    MAX_ATTEMPTS = MAX_ATTEMPTS_GET_ORDER_RESULT_FROM_SKB

    try:
        from app.services.route_services.orders import get_order_service

        service = get_order_service()

        await service.create_skb_order(order_id=data)  # type: ignore
    except Exception:
        logger.error("Failed to get order's result to SKB", exc_info=True)
        if attempt >= MAX_ATTEMPTS:
            logger.error("Max retries reached")
            return
        await stream_client.publish_to_redis(
            message=data,
            stream="order_get_result_from_skb_stream",
            headers={"attempt": attempt + 1},
            delay=timedelta(minutes=15),
        )
