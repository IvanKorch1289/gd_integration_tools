from asyncio import create_task
from typing import Any, Dict

from faststream.rabbit.fastapi import RabbitMessage
from faststream.redis.fastapi import Redis, RedisMessage

from app.config.settings import settings
from app.infra.clients.stream import stream_client
from app.schemas.base import EmailSchema
from app.schemas.route_schemas.orders import OrderSchemaIn, OrderSchemaOut


@stream_client.redis_router.subscriber(
    stream=settings.redis.get_stream_name("email")
)
async def handle_send_email(
    body: EmailSchema, msg: RedisMessage, redis: Redis
) -> None:
    from app.background_tasks.workflows import send_notification_workflow

    create_task(send_notification_workflow(body.model_dump()))


@stream_client.redis_router.subscriber(
    stream=settings.redis.get_stream_name("order-pipeline")
)
async def handle_order_pipeline(
    body: OrderSchemaOut, msg: RedisMessage, redis: Redis
) -> Any:
    from app.background_tasks.workflows import order_processing_workflow

    create_task(order_processing_workflow(body.model_dump()))


@stream_client.redis_router.subscriber(
    stream=settings.redis.get_stream_name("order-send")
)
async def handle_order_send_to_skb(
    body: OrderSchemaOut, msg: RedisMessage, redis: Redis
) -> Any:
    from app.background_tasks.workflows import create_skb_order_workflow

    create_task(create_skb_order_workflow(body.model_dump()))


@stream_client.redis_router.subscriber(
    stream=settings.redis.get_stream_name("order-get-result")
)
async def handle_order_get_result(
    body: OrderSchemaOut, msg: RedisMessage, redis: Redis
) -> Any:
    from app.background_tasks.workflows import get_skb_order_result_workflow

    create_task(get_skb_order_result_workflow(body.model_dump()))


@stream_client.rabbit_router.subscriber(
    settings.queue.get_topic_name("order-create")
)
async def handle_order_init_create(
    body: Dict[str, Any], msg: RabbitMessage
) -> Any:
    from app.services.route_services.orders import get_order_service
    from app.utils.utils import utilities

    raw_data = await utilities.decode_bytes(body)

    order_data = OrderSchemaIn.model_validate(raw_data)

    create_task(get_order_service().add(order_data.model_dump()))
