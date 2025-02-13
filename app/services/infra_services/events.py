from datetime import timedelta
from typing import Any

from faststream.redis.fastapi import Redis, RedisMessage

from app.config.constants import (
    MAX_ATTEMPTS_GET_ORDER_RESULT_FROM_SKB,
    MAX_ATTEMPTS_SEND_ORDER_TO_SKB,
)
from app.infra.clients.stream import stream_client
from app.schemas.base import EmailSchema


@stream_client.redis_router.subscriber(stream="email_send_stream", retry=3)
async def handle_send_email(
    body: EmailSchema, msg: RedisMessage, redis: Redis
) -> None:
    from app.services.infra_services.mail import get_mail_service

    mail_service = get_mail_service()
    # try:
    #     1 / 0
    #     await msg.ack(redis)
    try:
        await mail_service.send_email(
            to_emails=body.to_emails,
            subject=body.subject,
            message=body.message,
        )
    except Exception:
        await msg.nack(redis)
        raise


@stream_client.redis_router.subscriber(stream="order_send_to_skb_stream")
async def handle_order_send_to_skb(msg: int) -> Any:
    from app.services.route_services.orders import (
        OrderService,
        get_order_service,
    )

    service: OrderService = get_order_service()

    result = await service.create_skb_order(order_id=data)

    if not result.get("data", {}).get("Result"):
        raise RuntimeError("SKB order creation failed")

    return data


@stream_client.redis_router.subscriber(
    stream="order_get_result_from_skb_stream"
)
async def handle_order_get_result_from_skb(data: int) -> None:
    from app.services.route_services.orders import (
        OrderService,
        get_order_service,
    )

    service: OrderService = get_order_service()
    await service.get_order_result(order_id=data)
