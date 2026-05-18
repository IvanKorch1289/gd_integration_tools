"""NATSDLQWriter — публикует DLQEnvelope в NATS subject (Sprint 9 K2 W1).

Subject: ``dlq.{transport}``. JetStream persistence через ``js.publish``.
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

__all__ = ("NATSDLQWriter",)

logger = logging.getLogger(__name__)


class NATSDLQWriter:
    """Publish DLQ envelopes в NATS / JetStream.

    Args:
        jetstream: pre-initialized ``nats.aio.client.JetStreamContext``.
        subject_prefix: префикс (default ``"dlq."``).
    """

    def __init__(
        self,
        *,
        jetstream: Any,
        subject_prefix: str = "dlq.",
    ) -> None:
        self._js = jetstream
        self._subject_prefix = subject_prefix

    async def write(self, envelope: DLQEnvelope) -> None:
        subject = f"{self._subject_prefix}{envelope.transport}"
        payload = envelope.model_dump_json().encode("utf-8")
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
        except Exception:
            logger.exception(
                "dlq.nats.write_failed",
                extra={
                    "dlq_id": envelope.dlq_id,
                    "transport": envelope.transport,
                },
            )
            raise
