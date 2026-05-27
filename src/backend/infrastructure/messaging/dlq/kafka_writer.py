"""KafkaDLQWriter — публикует DLQEnvelope в Kafka topic (Sprint 9 K2 W1).

Topic-name: ``dlq.{transport}`` (например ``dlq.http``, ``dlq.soap``).
Сериализация: msgspec JSON (быстрее orjson по бенчмаркам Wave 7).

Зависит от ``aiokafka.AIOKafkaProducer`` через lazy-import (избегаем
import-cost в startup если Kafka не используется).
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

__all__ = ("KafkaDLQWriter",)

logger = logging.getLogger(__name__)


class KafkaDLQWriter:
    """Publish DLQ envelopes in Kafka topic.

    Args:
        producer: Pre-initialized AIOKafkaProducer (DI из composition root).
        topic_prefix: префикс topic'а (default ``"dlq."``).
        serializer: Опц. кастомный сериализатор (default — JSON через
            ``model_dump_json``).
    """

    def __init__(
        self, *, producer: Any, topic_prefix: str = "dlq.", serializer: Any = None
    ) -> None:
        self._producer = producer
        self._topic_prefix = topic_prefix
        self._serializer = serializer or self._default_serialize

    @staticmethod
    def _default_serialize(envelope: DLQEnvelope) -> bytes:
        return envelope.model_dump_json().encode("utf-8")

    async def write(self, envelope: DLQEnvelope) -> None:
        """Публикует envelope в ``dlq.{transport}``.

        Key = ``dlq_id`` (для idempotent-семантики с idempotent producer).
        """
        topic = f"{self._topic_prefix}{envelope.transport}"
        try:
            await self._producer.send_and_wait(
                topic,
                value=self._serializer(envelope),
                key=envelope.dlq_id.encode("utf-8"),
            )
        except Exception as _:
            logger.exception(
                "dlq.kafka.write_failed",
                extra={"dlq_id": envelope.dlq_id, "transport": envelope.transport},
            )
            raise
