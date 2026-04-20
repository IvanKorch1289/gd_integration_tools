"""Audit Event Log — кто/что/когда → ClickHouse через AsyncBatcher."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.interfaces import AsyncBatcher
from app.infrastructure.observability.correlation import get_correlation_id, get_tenant_id

__all__ = ("AuditEvent", "AuditEventLog", "emit_audit_event", "get_audit_log")

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AuditEvent:
    who: str
    what: str
    entity_type: str
    entity_id: str
    action: str
    when: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
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
        if not event.correlation_id:
            event.correlation_id = get_correlation_id()
        if not event.tenant_id:
            event.tenant_id = get_tenant_id()
        await self._batcher.add(event)

    async def _flush_to_clickhouse(self, events: list[AuditEvent]) -> None:
        try:
            from app.infrastructure.clients.storage.s3_pool.clickhouse import get_clickhouse_client

            client = get_clickhouse_client()
            rows = []
            for e in events:
                import json
                rows.append({
                    "who": e.who,
                    "what": e.what,
                    "entity_type": e.entity_type,
                    "entity_id": e.entity_id,
                    "action": e.action,
                    "when": e.when.isoformat(),
                    "before_data": json.dumps(e.before, default=str) if e.before else "",
                    "after_data": json.dumps(e.after, default=str) if e.after else "",
                    "correlation_id": e.correlation_id,
                    "tenant_id": e.tenant_id,
                    "metadata": json.dumps(e.metadata, default=str),
                })
            await client.insert(self._table, rows)
            logger.debug("Flushed %d audit events to ClickHouse", len(rows))
        except Exception as exc:
            logger.error("Audit flush to ClickHouse failed: %s", exc)

    async def query(
        self,
        entity_type: str | None = None,
        entity_id: str | None = None,
        who: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        from app.infrastructure.clients.storage.s3_pool.clickhouse import get_clickhouse_client

        client = get_clickhouse_client()

        # SQL injection protection: sanitize identifiers + escape string values
        def _escape(value: str) -> str:
            """Escape single quotes for ClickHouse string literals."""
            return str(value).replace("'", "''").replace("\\", "\\\\")

        def _safe_ident(name: str, allowed: set[str]) -> str:
            """Allowlist validation для имён колонок/таблиц."""
            if name not in allowed:
                raise ValueError(f"Invalid identifier: {name}")
            return name

        # Валидация table name через allowlist
        _safe_table = _safe_ident(self._table, {"audit_events", "audit_log"})

        # Валидация limit (int, bounded)
        try:
            safe_limit = max(1, min(int(limit), 10000))
        except (TypeError, ValueError):
            safe_limit = 100

        conditions = []
        if entity_type:
            conditions.append(f"entity_type = '{_escape(entity_type)}'")
        if entity_id:
            conditions.append(f"entity_id = '{_escape(entity_id)}'")
        if who:
            conditions.append(f"who = '{_escape(who)}'")

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM {_safe_table}{where} ORDER BY when DESC LIMIT {safe_limit}"
        return await client.query(sql)


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
        who=who, what=what, entity_type=entity_type,
        entity_id=entity_id, action=action,
        before=before, after=after, metadata=metadata,
    )
    await get_audit_log().emit(event)
