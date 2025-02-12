from datetime import timedelta
from functools import wraps
from typing import Any

from app.config.constants import (
    MAX_ATTEMPTS_GET_ORDER_RESULT_FROM_SKB,
    MAX_ATTEMPTS_SEND_ORDER_TO_SKB,
)
from app.infra.clients.stream import stream_client


@stream_client.redis_broker.subscriber("email_send_stream")
@stream_client.retry_with_backoff(
    max_attempts=3,
    delay=timedelta(seconds=60),
    stream="email_send_stream",
)
async def handle_send_email(data: Any) -> None:
    from app.services.infra_services.mail import get_mail_service

    mail_service = get_mail_service()
    await mail_service.send_email(
        to_emails=data["to_emails"],
        subject=data["subject"],
        message=data["message"],
    )


# Общий декоратор для workflow
def order_workflow(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        result = await func(*args, **kwargs)
        if func.__name__ == "handle_order_send_to_skb":
            await stream_client.publish_with_delay(
                stream="order_get_result_from_skb_stream",
                message=result,
                delay=timedelta(minutes=30),
            )
        return result

    return wrapper


@order_workflow
@stream_client.redis_broker.subscriber("order_send_to_skb_stream")
@stream_client.retry_with_backoff(
    max_attempts=MAX_ATTEMPTS_SEND_ORDER_TO_SKB,
    delay=timedelta(minutes=5),
    stream="order_send_to_skb_stream",
)
async def handle_order_send_to_skb(data: Any) -> Any:
    from app.services.route_services.orders import (
        OrderService,
        get_order_service,
    )

    service: OrderService = get_order_service()
    result = await service.create_skb_order(order_id=data)

    if not result.get("data", {}).get("Result"):
        raise RuntimeError("SKB order creation failed")

    return data


@stream_client.redis_broker.subscriber("order_get_result_from_skb_stream")
@stream_client.retry_with_backoff(
    max_attempts=MAX_ATTEMPTS_GET_ORDER_RESULT_FROM_SKB,
    delay=timedelta(minutes=15),
    stream="order_get_result_from_skb_stream",
)
async def handle_order_get_result_from_skb(data: Any) -> None:
    from app.services.route_services.orders import (
        OrderService,
        get_order_service,
    )

    service: OrderService = get_order_service()
    await service.get_order_result(order_id=data)
