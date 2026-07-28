"""NATSDLQWriter — публикует DLQEnvelope в NATS subject (Sprint 9 K2 W1).

Subject: ``dlq.{transport}``. JetStream persistence через ``js.publish``.
Сериализация: msgspec JSON (быстрее orjson по бенчмаркам Wave 7).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.resilience.breaker import BreakerSpec, get_breaker_registry
from src.backend.core.security.connector_auth import require_capability
from src.backend.core.serialization.msgspec_hotpath import encode_json
from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

__all__ = ("NATSDLQWriter",)

logger = get_logger(__name__)


def _get_nats_dlq_breaker() -> Any:
    """S204 retro-audit B23: CB singleton для NATS DLQ writer."""
    return get_breaker_registry().get_or_create(
        "nats_dlq_writer",
        BreakerSpec(name="nats_dlq_writer", failure_threshold=5, recovery_timeout=30.0),
    )


class NATSDLQWriter:
    """Publish DLQ envelopes в NATS / JetStream.

    Args:
        jetstream: pre-initialized ``nats.aio.client.JetStreamContext``.
        subject_prefix: префикс (default ``"dlq."``).
    """

    def __init__(self, *, jetstream: Any, subject_prefix: str = "dlq.") -> None:
        self._js = jetstream
        self._subject_prefix = subject_prefix

    @require_capability("dlq.write", action="write")
    async def write(self, envelope: DLQEnvelope) -> None:
        """Метод write (см. signature)."""
        subject = f"{self._subject_prefix}{envelope.transport}"
        payload = encode_json(envelope.model_dump(mode="json"))
        # S204 retro-audit B23: wrap publish with Purgatory CB.
        breaker = _get_nats_dlq_breaker()
        async with breaker.guard():
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
