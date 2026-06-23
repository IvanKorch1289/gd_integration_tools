"""Audit Event Log — кто/что/когда → ClickHouse через AsyncBatcher."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.backend.core.interfaces import AsyncBatcher
from src.backend.core.logging import get_logger
from src.backend.infrastructure.observability.correlation import (
    get_correlation_id,
    get_tenant_id,
)

# S44 W5: facade import через core.observability (was string-bypass
# dynamic import 'src.backend.services.io.indexers.log_indexer' чтобы
# обойти static AST layer linter). Теперь прямой static import.

__all__ = ("AuditEvent", "AuditEventLog", "emit_audit_event", "get_audit_log")

logger = get_logger(__name__)


@dataclass(slots=True)
class AuditEvent:
    who: str
    what: str
    entity_type: str
    entity_id: str
    action: str
    when: datetime = field(default_factory=lambda: datetime.now(UTC))
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    correlation_id: str = ""
    tenant_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class AuditEventLog:
    """Записывает audit events в ClickHouse через batch insert."""

    def __init__(self, table: str = "audit_events", batch_size: int = 50) -> None:
        self._table = table
        self._batcher = AsyncBatcher(
            flush_fn=self._flush_to_clickhouse,
            batch_size=batch_size,
            flush_interval_seconds=5.0,
        )

    async def start(self) -> None:
        await self._batcher.start()
        logger.info("AuditEventLog started (table=%s)", self._table)

    async def stop(self) -> None:
        await self._batcher.stop()
        logger.info("AuditEventLog stopped")

    async def emit(self, event: AuditEvent) -> None:
        """Emit an audit event.

        Args:
            event: Audit event to emit.
        """
        if not event.correlation_id:
            event.correlation_id = get_correlation_id()
        if not event.tenant_id:
            event.tenant_id = get_tenant_id()
        await self._batcher.add(event)

    async def _flush_to_clickhouse(self, events: list[AuditEvent]) -> None:
        try:
            from src.backend.infrastructure.clients.storage.clickhouse import (
                get_clickhouse_client,
            )

            client = get_clickhouse_client()
            rows = []
            from src.backend.infrastructure.audit._json_codec import dumps_str

            for e in events:
                rows.append(
                    {
                        "who": e.who,
                        "what": e.what,
                        "entity_type": e.entity_type,
                        "entity_id": e.entity_id,
                        "action": e.action,
                        "when": e.when.isoformat(),
                        "before_data": dumps_str(e.before) if e.before else "",
                        "after_data": dumps_str(e.after) if e.after else "",
                        "correlation_id": e.correlation_id,
                        "tenant_id": e.tenant_id,
                        "metadata": dumps_str(e.metadata),
                    }
                )
            await client.insert(self._table, rows)
            logger.debug("Flushed %d audit events to ClickHouse", len(rows))
        except Exception as exc:
            logger.error("Audit flush to ClickHouse failed: %s", exc)

        # Wave 9.3.1: secondary indexing в Elasticsearch (best-effort).
        # S44 W5: facade import через core.observability (was string-bypass).
        try:
            from src.backend.core.observability.log_indexer import get_log_indexer

            indexer = get_log_indexer()
            await indexer.index_batch(events)
        except Exception as es_exc:
            logger.warning("LogIndexer.index_batch failed: %s", es_exc)

    async def query(
        self,
        entity_type: str | None = None,
        entity_id: str | None = None,
        who: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """SELECT с фильтрами для audit_events / audit_log.

        ponytail: S61 W4 defense-in-depth был заменён на полноценные
        bound parameters через ClickHouse {name} syntax вместо _escape().
        ClickHouse HTTP API поддерживает {name} placeholders, которые
        корректно экранируются на уровне протокола.

        Защита от SQL injection:
        1. _safe_ident — allowlist для table name (audit_events / audit_log)
        2. Bound parameters через ClickHouse {name} syntax
        3. safe_limit — int(limit) bounded к [1, 10000]
        """
        from src.backend.infrastructure.clients.storage.clickhouse import (
            get_clickhouse_client,
        )

        client = get_clickhouse_client()

        def _safe_ident(name: str, allowed: set[str]) -> str:
            """Allowlist validation для table name."""
            if name not in allowed:
                raise ValueError(f"Invalid identifier: {name}")
            return name

        # Валидация table name через allowlist
        safe_table = _safe_ident(self._table, {"audit_events", "audit_log"})

        # Валидация limit (int, bounded)
        try:
            safe_limit = max(1, min(int(limit), 10000))
        except TypeError, ValueError:
            safe_limit = 100

        # Build query с bound parameters через {name} syntax
        params: dict[str, Any] = {}
        conditions = []

        if entity_type:
            params["entity_type"] = entity_type
            conditions.append("entity_type = {entity_type:String}")
        if entity_id:
            params["entity_id"] = entity_id
            conditions.append("entity_id = {entity_id:String}")
        if who:
            params["who"] = who
            conditions.append("who = {who:String}")

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM {safe_table}{where} ORDER BY when DESC LIMIT {safe_limit}"  # noqa: S608
        return await client.query(sql, params)


_audit_log: AuditEventLog | None = None


def get_audit_log() -> AuditEventLog:
    global _audit_log
    if _audit_log is None:
        _audit_log = AuditEventLog()
    return _audit_log


async def emit_audit_event(
    who: str,
    what: str,
    entity_type: str,
    entity_id: str,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    **metadata: Any,
) -> None:
    event = AuditEvent(
        who=who,
        what=what,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        before=before,
        after=after,
        metadata=metadata,
    )
    await get_audit_log().emit(event)
