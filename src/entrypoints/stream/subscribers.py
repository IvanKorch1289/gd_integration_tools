from faststream.rabbit.fastapi import RabbitMessage
from faststream.redis.fastapi import Redis, RedisMessage

from src.core.config.settings import settings
from src.core.di.providers import get_stream_client_provider, get_stream_logger_provider
from src.entrypoints.api.generator.registry import action_handler_registry
from src.schemas.invocation import ActionCommandSchema

__all__ = ("handle_universal_redis_action", "handle_universal_rabbit_action")

stream_client = get_stream_client_provider()
stream_logger = get_stream_logger_provider()


@stream_client.redis_router.subscriber(  # type: ignore
    stream=settings.redis.get_stream_name("dsl-events")
)
async def handle_universal_redis_action(
    body: dict, msg: RedisMessage, redis: Redis
) -> None:
    """Универсальный обработчик DSL-команд из Redis."""
    try:
        command = ActionCommandSchema.model_validate(body)
        stream_logger.info(
            "Redis DSL action received action=%s correlation_id=%s",
            command.action,
            getattr(msg, "correlation_id", None),
        )
        await action_handler_registry.dispatch(command)
    except Exception as exc:
        stream_logger.error(f"Failed to process Redis DSL action: {exc}", exc_info=True)


@stream_client.rabbit_router.subscriber(settings.queue.get_queue_name("dsl-actions"))  # type: ignore
async def handle_universal_rabbit_action(body: dict, msg: RabbitMessage) -> None:
    """Универсальный обработчик DSL-команд из RabbitMQ."""
    try:
        command = ActionCommandSchema.model_validate(body)
        stream_logger.info(
            "RabbitMQ DSL action received action=%s correlation_id=%s",
            command.action,
            getattr(msg, "correlation_id", None),
        )
        await action_handler_registry.dispatch(command)
    except Exception as exc:
        stream_logger.error(
            f"Failed to process RabbitMQ DSL action: {exc}", exc_info=True
        )
