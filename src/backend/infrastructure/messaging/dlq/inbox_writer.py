"""InboxDLQWriter — пишет DLQEnvelope в Postgres table (Sprint 9 K2 W1).

Используется когда messaging не настроен (dev_light) или как fallback при
недоступности Kafka/RabbitMQ/NATS. Table ``dlq_inbox`` (см. миграции).
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

__all__ = ("InboxDLQWriter",)

logger = logging.getLogger(__name__)


class InboxDLQWriter:
    """Postgres-backed writer.

    Args:
        session_factory: async ``sessionmaker`` (DI).
        table_name: имя таблицы (default ``"dlq_inbox"``).
    """

    def __init__(self, *, session_factory: Any, table_name: str = "dlq_inbox") -> None:
        self._session_factory = session_factory
        self._table = table_name

    async def write(self, envelope: DLQEnvelope) -> None:
        from sqlalchemy import text  # type: ignore[import-untyped]

        sql = text(
            f"""
            INSERT INTO {self._table} (
                dlq_id, transport, trace_id, tenant_id, route_id,
                original_payload, error_class, error_message, reason,
                retry_count, first_failed_at, last_failed_at, metadata
            )
            VALUES (
                :dlq_id, :transport, :trace_id, :tenant_id, :route_id,
                :original_payload, :error_class, :error_message, :reason,
                :retry_count, :first_failed_at, :last_failed_at, :metadata
            )
            ON CONFLICT (dlq_id) DO NOTHING
            """
        )
        params = envelope.model_dump()
        # SQLAlchemy JSON-сериализация поля metadata + original_payload
        params["metadata"] = params.get("metadata", {})

        try:
            async with self._session_factory() as session:
                await session.execute(sql, params)
                await session.commit()
        except Exception as _:
            logger.exception(
                "dlq.inbox.write_failed",
                extra={"dlq_id": envelope.dlq_id, "transport": envelope.transport},
            )
            raise
