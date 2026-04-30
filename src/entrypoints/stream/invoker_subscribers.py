"""MQ entry-point адаптеры для :class:`Invoker` (W22 этап B).

Подписчики на Redis Streams и RabbitMQ-очередь, которые принимают
сериализованный :class:`InvocationRequest` (формат
:func:`src.services.execution.invoker._serialize_request`) и пробрасывают
его в Invoker.

Topic/queue имена:

* Redis Stream — :func:`settings.redis.get_stream_name('invocations-in')`
* RabbitMQ queue — :func:`settings.queue.get_queue_name('invocations-in')`

Результат публикуется через ``reply_channel``, указанный в request
(по умолчанию ``api`` — polling-канал; для durable обратной связи —
``queue`` с ``metadata.queue_topic``).
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.fastapi import RabbitMessage
from faststream.redis.fastapi import Redis, RedisMessage

from src.core.config.settings import settings
from src.infrastructure.clients.messaging.stream import stream_client
from src.infrastructure.external_apis.logging_service import stream_logger

__all__ = ("handle_redis_invocation", "handle_rabbit_invocation")


@stream_client.redis_router.subscriber(  # type: ignore
    stream=settings.redis.get_stream_name("invocations-in")
)
async def handle_redis_invocation(
    body: dict[str, Any], msg: RedisMessage, redis: Redis
) -> None:
    """Подписчик Redis Streams: принимает InvocationRequest и вызывает Invoker."""
    await _dispatch_invocation_message(
        body, correlation_id=getattr(msg, "correlation_id", None), source="redis"
    )


@stream_client.rabbit_router.subscriber(  # type: ignore
    settings.queue.get_queue_name("invocations-in")
)
async def handle_rabbit_invocation(body: dict[str, Any], msg: RabbitMessage) -> None:
    """Подписчик RabbitMQ: принимает InvocationRequest и вызывает Invoker."""
    await _dispatch_invocation_message(
        body, correlation_id=getattr(msg, "correlation_id", None), source="rabbit"
    )


async def _dispatch_invocation_message(
    body: dict[str, Any], *, correlation_id: str | None, source: str
) -> None:
    """Десериализует body и пробрасывает в Invoker.

    Ошибки парсинга → лог + drop (consumer не должен retry'ить bad message).
    Ошибки Invoker → уже залогированы внутри; consumer ack'ает сообщение
    в любом случае, чтобы избежать infinite redelivery — повторная попытка
    через :class:`InvocationStatus.ERROR` в reply-канале.
    """
    from src.services.execution.invoker import _deserialize_request, get_invoker

    try:
        request = _deserialize_request(body)
    except (KeyError, ValueError, TypeError) as exc:
        stream_logger.warning(
            "MQ invocation: невалидный body source=%s correlation_id=%s err=%s",
            source,
            correlation_id,
            exc,
        )
        return
    stream_logger.info(
        "MQ invocation accepted source=%s action=%s id=%s correlation_id=%s",
        source,
        request.action,
        request.invocation_id,
        correlation_id,
    )
    invoker = get_invoker()
    try:
        await invoker.invoke(request)
    except Exception:  # noqa: BLE001
        stream_logger.exception(
            "MQ invocation: Invoker.invoke failed source=%s id=%s",
            source,
            request.invocation_id,
        )
