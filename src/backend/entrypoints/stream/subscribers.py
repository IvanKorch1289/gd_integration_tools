from __future__ import annotations

from typing import Any

from faststream.rabbit.fastapi import RabbitMessage
from faststream.redis.fastapi import Redis, RedisChannelMessage

from src.backend.core.config.settings import settings
from src.backend.core.di.providers import (
    get_stream_client_provider,
    get_stream_logger_provider,
)
from src.backend.entrypoints.api.generator.registry import action_handler_registry
from src.backend.entrypoints.stream._dlq_helper import enqueue_mq_poison_message
from src.backend.schemas.invocation import ActionCommandSchema

__all__ = ("handle_universal_rabbit_action", "handle_universal_redis_action")

stream_client = get_stream_client_provider()
stream_logger = get_stream_logger_provider()


@stream_client.redis_router.subscriber(
    stream=settings.redis.get_stream_name("dsl-events"),
)
async def handle_universal_redis_action(
    body: dict, msg: RedisChannelMessage, redis: Redis,
) -> None:
    """Универсальный обработчик DSL-команд из Redis.

    cycle-5/D-AUDIT-504: при exception в handler'е enqueue poison message
    в DLQ (B-17 fail-loud pattern). Если DLQ writer не настроен в
    composition root — log warning (silent fallback fail-loud).
    """
    correlation_id = getattr(msg, "correlation_id", None)
    try:
        command = ActionCommandSchema.model_validate(body)
        stream_logger.info(
            "Redis DSL action received action=%s correlation_id=%s",
            command.action,
            correlation_id,
        )
        await action_handler_registry.dispatch(command)
    except Exception as exc:
        await enqueue_mq_poison_message(
            exc=exc,
            body=body,
            source="redis",
            route_id=settings.redis.get_stream_name("dsl-events"),
            correlation_id=correlation_id,
            logger=stream_logger,
        )
        stream_logger.error(
            "Failed to process Redis DSL action: poison_message=%s "
            "tenant_id=%s correlation_id=%s err=%s",
            _summarize_poison(body),
            None,
            correlation_id,
            exc,
            exc_info=True,
        )


@stream_client.rabbit_router.subscriber(settings.queue.get_queue_name("dsl-actions"))
async def handle_universal_rabbit_action(body: dict, msg: RabbitMessage) -> None:
    """Универсальный обработчик DSL-команд из RabbitMQ.

    cycle-5/D-AUDIT-504: при exception в handler'е enqueue poison message
    в DLQ (B-17 fail-loud pattern). Если DLQ writer не настроен в
    composition root — log warning (silent fallback fail-loud).
    """
    correlation_id = getattr(msg, "correlation_id", None)
    try:
        command = ActionCommandSchema.model_validate(body)
        stream_logger.info(
            "RabbitMQ DSL action received action=%s correlation_id=%s",
            command.action,
            correlation_id,
        )
        await action_handler_registry.dispatch(command)
    except Exception as exc:
        await enqueue_mq_poison_message(
            exc=exc,
            body=body,
            source="rabbit",
            route_id=settings.queue.get_queue_name("dsl-actions"),
            correlation_id=correlation_id,
            logger=stream_logger,
        )
        stream_logger.error(
            "Failed to process RabbitMQ DSL action: poison_message=%s "
            "tenant_id=%s correlation_id=%s err=%s",
            _summarize_poison(body),
            None,
            correlation_id,
            exc,
            exc_info=True,
        )


def _summarize_poison(body: Any, *, max_len: int = 256) -> str:
    """Краткое summary body для log/error message (truncate to ``max_len``)."""
    try:
        rendered = repr(body)
    except (TypeError, ValueError) as repr_exc:
        # cycle-9/D-AUDIT-1011: narrow exceptions + observability.
        # TypeError для unrepresentable type, ValueError для invalid
        # repr value.
        import logging
        logging.getLogger(__name__).debug(
            "stream_subscribers.summarize_poison_fallback",
            extra={"error": str(repr_exc)},
        )
        rendered = "<unrepresentable body>"
    if len(rendered) > max_len:
        return rendered[: max_len - 3] + "..."
    return rendered
