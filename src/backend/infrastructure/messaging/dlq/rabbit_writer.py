"""RabbitDLQWriter — публикует DLQEnvelope в RabbitMQ queue (Sprint 9 K2 W1).

Queue-name: ``dlq.{transport}``. Persistent сообщения (``delivery_mode=2``).
Использует aio-pika.

Сериализация: msgspec JSON (быстрее orjson по бенчмаркам Wave 7).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.serialization.msgspec_hotpath import encode_json
from src.backend.core.logging import get_logger
from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

__all__ = ("RabbitDLQWriter",)

logger = get_logger(__name__)


class RabbitDLQWriter:
    """Publish DLQ envelopes в RabbitMQ.

    Args:
        channel: pre-initialized ``aio_pika.Channel`` (DI).
        exchange_name: Имя exchange'а (``""`` = default exchange).
        queue_prefix: префикс queue (default ``"dlq."``).
    """

    def __init__(
        self, *, channel: Any, exchange_name: str = "", queue_prefix: str = "dlq."
    ) -> None:
        self._channel = channel
        self._exchange_name = exchange_name
        self._queue_prefix = queue_prefix

    async def write(self, envelope: DLQEnvelope) -> None:
        from aio_pika import DeliveryMode, Message

        routing_key = f"{self._queue_prefix}{envelope.transport}"
        payload = encode_json(envelope.model_dump(mode="json"))
        message = Message(
            body=payload,
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=envelope.dlq_id,
            content_type="application/json",
            headers={
                "transport": envelope.transport,
                "reason": str(envelope.reason),
                "tenant_id": envelope.tenant_id or "",
                "trace_id": envelope.trace_id or "",
            },
        )
        try:
            exchange = (
                self._channel.default_exchange
                if not self._exchange_name
                else await self._channel.get_exchange(self._exchange_name)
            )
            await exchange.publish(message, routing_key=routing_key)
        except Exception as _:
            logger.exception(
                "dlq.rabbit.write_failed",
                extra={"dlq_id": envelope.dlq_id, "transport": envelope.transport},
            )
            raise
