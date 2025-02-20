from typing import Any

from faststream.redis.fastapi import Redis, RedisMessage

from app.infra.clients.stream import stream_client
from app.schemas.base import EmailSchema
from app.schemas.route_schemas.orders import OrderSchemaOut


@stream_client.redis_router.subscriber(stream="email_send_stream")
async def handle_send_email(
    body: EmailSchema, msg: RedisMessage, redis: Redis
) -> None:
    from app.background_tasks.tasks import send_mail_task

    await send_mail_task.kiq(body.model_dump())


@stream_client.redis_router.subscriber(stream="order_send_to_skb_stream")
async def handle_order_send_to_skb(
    body: OrderSchemaOut, msg: RedisMessage, redis: Redis
) -> Any:
    from app.background_tasks.tasks import (  # skb_order_pipeline,
        create_skb_order_task,
    )

    await create_skb_order_task.kiq(body.model_dump())
    # await skb_order_pipeline.kiq(body)
