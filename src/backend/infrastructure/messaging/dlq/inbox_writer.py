"""InboxDLQWriter — пишет DLQEnvelope в Postgres table (Sprint 9 K2 W1).

Используется когда messaging не настроен (dev_light) или как fallback при
недоступности Kafka/RabbitMQ/NATS. Table ``dlq_inbox`` (см. миграции).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.resilience.breaker import BreakerSpec, get_breaker_registry
from src.backend.core.utils.sql_identifiers import validate_identifier
from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

__all__ = ("InboxDLQWriter",)

logger = get_logger(__name__)


def _get_inbox_dlq_breaker() -> Any:
    """S204 retro-audit B23: CB singleton для Inbox (Postgres) DLQ writer.

    PG-вставки могут длительно отказывать при connectivity-проблемах;
    без CB каждое DLQ-событие будет повторно падать на timeout.
    """
    return get_breaker_registry().get_or_create(
        "inbox_dlq_writer",
        BreakerSpec(
            name="inbox_dlq_writer", failure_threshold=5, recovery_timeout=30.0
        ),
    )


class InboxDLQWriter:
    """Postgres-backed writer.

    Args:
        session_factory: async ``sessionmaker`` (DI).
        table_name: имя таблицы (default ``"dlq_inbox"``).

    Raises:
        ValueError: Если ``table_name`` — не валидный SQL-идентификатор
            (S-30, Wave 13 Q18 — fail-fast до первого INSERT).

    """

    def __init__(self, *, session_factory: Any, table_name: str = "dlq_inbox") -> None:
        self._session_factory = session_factory
        # S-30 (Wave 13, Q18): имя таблицы подставляется в SQL через
        # f-string — bind-параметры применимы только к значениям.
        self._table = validate_identifier(table_name, context="dlq.inbox_writer.table")

    async def write(self, envelope: DLQEnvelope) -> None:
        """Метод write (см. signature)."""
        from sqlalchemy import text

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
            """  # noqa: S608  # nosec B608 — table: allowlist (validate_identifier в __init__), значения: bind-параметры
        )
        params = envelope.model_dump()
        # SQLAlchemy JSON-сериализация поля metadata + original_payload
        params["metadata"] = params.get("metadata", {})

        # S204 retro-audit B23: wrap PG-execute with Purgatory CB.
        breaker = _get_inbox_dlq_breaker()
        async with breaker.guard():
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
