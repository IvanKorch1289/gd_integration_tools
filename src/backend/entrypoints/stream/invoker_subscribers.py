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

cycle-5/D-AUDIT-504: B-17 fail-loud DLQ handoff для MQ consumer.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.fastapi import RabbitMessage
from faststream.redis.fastapi import Redis, RedisChannelMessage

from src.backend.core.config.settings import settings
from src.backend.core.di.providers import (
    get_stream_client_provider,
    get_stream_logger_provider,
)
from src.backend.entrypoints.stream._dlq_helper import enqueue_mq_poison_message

__all__ = ("handle_rabbit_invocation", "handle_redis_invocation")

stream_client = get_stream_client_provider()
stream_logger = get_stream_logger_provider()


@stream_client.redis_router.subscriber(
    stream=settings.redis.get_stream_name("invocations-in")
)
async def handle_redis_invocation(
    body: dict[str, Any], msg: RedisChannelMessage, redis: Redis
) -> None:
    """Подписчик Redis Streams: принимает InvocationRequest и вызывает Invoker."""
    await _dispatch_invocation_message(
        body, correlation_id=getattr(msg, "correlation_id", None), source="redis"
    )


@stream_client.rabbit_router.subscriber(settings.queue.get_queue_name("invocations-in"))
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
    from src.backend.services.execution.invoker import _deserialize_request, get_invoker

    try:
        request = _deserialize_request(body)
    except (KeyError, ValueError, TypeError) as exc:
        # cycle-5/D-AUDIT-504: невалидный body → enqueue в DLQ для replay/debug
        # (B-17 fail-loud pattern). Раньше silently drop'ался.
        await enqueue_mq_poison_message(
            exc=exc,
            body=body,
            source=source,
            route_id=(
                settings.redis.get_stream_name("invocations-in")
                if source == "redis"
                else settings.queue.get_queue_name("invocations-in")
            ),
            correlation_id=correlation_id,
            logger=stream_logger,
        )
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
    except Exception as exc:
        # cycle-5/D-AUDIT-504: B-17 fail-loud DLQ handoff для MQ consumer.
        # Enqueue poison message с tenant_id/correlation_id/invocation_id,
        # затем logger.error. Не raise'им — handler уже в except-блоке,
        # чтобы не маскировать исходную ошибку.
        await enqueue_mq_poison_message(
            exc=exc,
            body=body,
            source=source,
            route_id=(
                settings.redis.get_stream_name("invocations-in")
                if source == "redis"
                else settings.queue.get_queue_name("invocations-in")
            ),
            correlation_id=correlation_id,
            tenant_id=_extract_tenant_id(request),
            logger=stream_logger,
        )
        stream_logger.exception(
            "MQ invocation: Invoker.invoke failed source=%s id=%s "
            "correlation_id=%s tenant_id=%s poison_message=%s",
            source,
            request.invocation_id,
            correlation_id,
            _extract_tenant_id(request),
            _summarize_poison(body),
        )


def _summarize_poison(body: Any, *, max_len: int = 256) -> str:
    """Краткое summary body для error log (truncate to ``max_len``)."""
    try:
        rendered = repr(body)
    except (TypeError, ValueError) as repr_exc:
        # cycle-9/D-AUDIT-1012: narrow exceptions + observability (mirror
        # D-AUDIT-1011).
        # TypeError для unrepresentable type, ValueError для invalid
        # repr value.
        import logging
        logging.getLogger(__name__).debug(
            "stream_invoker_subscribers.summarize_poison_fallback",
            extra={"error": str(repr_exc)},
        )
        rendered = "<unrepresentable body>"
    if len(rendered) > max_len:
        return rendered[: max_len - 3] + "..."
    return rendered


def _extract_tenant_id(request: Any) -> str | None:
    """Извлекает ``tenant_id`` из ``InvocationRequest``.

    Поля ``tenant_id`` в dataclass нет — обычно кладут в ``metadata`` dict.
    Используем ``getattr(metadata, "get", ...)`` чтобы не падать, если
    ``metadata`` отсутствует или имеет другой тип (mock, None).
    """
    metadata = getattr(request, "metadata", None)
    if metadata is None:
        return None
    getter = getattr(metadata, "get", None)
    if getter is None or not callable(getter):
        return None
    value = getter("tenant_id")
    return value if isinstance(value, str) else None
