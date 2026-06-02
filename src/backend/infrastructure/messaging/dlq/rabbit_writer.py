"""RabbitDLQWriter — публикует DLQEnvelope в RabbitMQ queue (Sprint 9 K2 W1).

Queue-name: ``dlq.{transport}``. Persistent сообщения (``delivery_mode=2``).
Использует aio-pika.
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

__all__ = ("RabbitDLQWriter",)

logger = logging.getLogger(__name__)


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
        payload = envelope.model_dump_json().encode("utf-8")
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
