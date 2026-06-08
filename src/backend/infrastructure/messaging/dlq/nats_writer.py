"""NATSDLQWriter — публикует DLQEnvelope в NATS subject (Sprint 9 K2 W1).

Subject: ``dlq.{transport}``. JetStream persistence через ``js.publish``.
Сериализация: msgspec JSON (быстрее orjson по бенчмаркам Wave 7).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.serialization.msgspec_hotpath import encode_json
from src.backend.infrastructure.logging.factory import get_logger
from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

__all__ = ("NATSDLQWriter",)

logger = get_logger(__name__)


class NATSDLQWriter:
    """Publish DLQ envelopes в NATS / JetStream.

    Args:
        jetstream: pre-initialized ``nats.aio.client.JetStreamContext``.
        subject_prefix: префикс (default ``"dlq."``).
    """

    def __init__(self, *, jetstream: Any, subject_prefix: str = "dlq.") -> None:
        self._js = jetstream
        self._subject_prefix = subject_prefix

    async def write(self, envelope: DLQEnvelope) -> None:
        subject = f"{self._subject_prefix}{envelope.transport}"
        payload = encode_json(envelope.model_dump(mode="json"))
        try:
            await self._js.publish(
                subject,
                payload,
                headers={
                    "Nats-Msg-Id": envelope.dlq_id,
                    "X-Transport": envelope.transport,
                    "X-Tenant": envelope.tenant_id or "",
                    "X-Trace": envelope.trace_id or "",
                },
            )
        except Exception as _:
            logger.exception(
                "dlq.nats.write_failed",
                extra={"dlq_id": envelope.dlq_id, "transport": envelope.transport},
            )
            raise
