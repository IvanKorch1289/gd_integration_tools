from typing import Any

from faststream.rabbit.fastapi import RabbitMessage
from faststream.redis.fastapi import Redis, RedisMessage

from app.infra.clients.stream import stream_client
from app.schemas.base import EmailSchema
from app.schemas.route_schemas.orders import OrderSchemaIn, OrderSchemaOut
from app.utils.logging_service import app_logger


@stream_client.redis_router.subscriber(stream="email_send_stream")
async def handle_send_email(
    body: EmailSchema, msg: RedisMessage, redis: Redis
) -> None:
    from app.background_tasks.workflows import send_notification_workflow

    await send_notification_workflow(body.model_dump())


@stream_client.redis_router.subscriber(stream="order_start_pipeline")
async def handle_order_pipeline(
    body: OrderSchemaOut, msg: RedisMessage, redis: Redis
) -> Any:
    from app.background_tasks.workflows import order_processing_workflow

    await order_processing_workflow(body.model_dump())


@stream_client.redis_router.subscriber(stream="order_send_to_skb_stream")
async def handle_order_send_to_skb(
    body: OrderSchemaOut, msg: RedisMessage, redis: Redis
) -> Any:
    from app.background_tasks.workflows import create_skb_order_workflow

    await create_skb_order_workflow(body.model_dump())


@stream_client.redis_router.subscriber(stream="order_get_result_from_skb")
async def handle_order_get_result(
    body: OrderSchemaOut, msg: RedisMessage, redis: Redis
) -> Any:
    from app.background_tasks.workflows import get_skb_order_result_workflow

    await get_skb_order_result_workflow(body.model_dump())


@stream_client.rabbit_router.subscriber("order-init-create-topic")
async def handle_order_init_create(body: Any, msg: RabbitMessage) -> Any:
    from app.services.route_services.orders import get_order_service
    from app.utils.utils import utilities

    try:
        # Парсим сырые данные в модель
        raw_data = await utilities.decode_bytes(body)

        order_data = OrderSchemaIn.model_validate(raw_data)

        await get_order_service().add(order_data.model_dump())

    except Exception:
        app_logger.error("Error processing message", exc_info=True)
