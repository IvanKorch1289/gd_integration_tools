from typing import Any

from faststream.redis.fastapi import Redis, RedisMessage

from app.infra.clients.stream import stream_client
from app.schemas.base import EmailSchema


@stream_client.redis_router.subscriber(stream="email_send_stream")
async def handle_send_email(
    body: EmailSchema, msg: RedisMessage, redis: Redis
) -> None:
    try:
        from app.utils.tasks import send_mail_task

        await send_mail_task.kiq(body.model_dump())

        await msg.ack(redis)
    except Exception:
        await msg.nack(redis)
        raise


@stream_client.redis_router.subscriber(stream="order_send_to_skb_stream")
async def handle_order_send_to_skb(
    body: int, msg: RedisMessage, redis: Redis
) -> Any:
    from app.utils.tasks import skb_order_pipeline

    await skb_order_pipeline.kiq(body)
