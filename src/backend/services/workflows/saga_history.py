"""Saga compensation history — Sprint 12 K3 W6.

API:
    * :class:`SagaHistoryRecord` — one saga timeline entry.
    * :func:`get_saga_history(workflow_id, limit)` — читает workflow_audit
      ClickHouse + строит timeline (compensation_start / _complete / _fail).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("SagaHistoryRecord", "aggregate_saga_stats", "get_saga_history")

_logger = get_logger("services.workflows.saga_history")


@dataclass(frozen=True, slots=True)
class SagaHistoryRecord:
    """Одна запись saga timeline для UI."""

    event_id: str
    event_type: str
    workflow_id: str
    tenant_id: str | None
    payload: dict[str, Any]
    created_at: datetime
    duration_ms: int | None = None


async def _get_clickhouse_client(factory: Any | None = None) -> Any:
    if factory is not None:
        return await factory()
    from clickhouse_connect import get_async_client

    from src.backend.core.config import settings

    host = (
        getattr(settings.clickhouse, "host", "localhost")
        if hasattr(settings, "clickhouse")
        else "localhost"
    )
    port = (
        getattr(settings.clickhouse, "port", 8123)
        if hasattr(settings, "clickhouse")
        else 8123
    )
    database = (
        getattr(settings.clickhouse, "database", "default")
        if hasattr(settings, "clickhouse")
        else "default"
    )
    return await get_async_client(host=host, port=port, database=database)


async def get_saga_history(
    workflow_id: str, *, limit: int = 50, client_factory: Any | None = None
) -> list[SagaHistoryRecord]:
    """Возвращает timeline saga events для конкретного workflow_id."""
    import json

    limit = max(1, min(limit, 1000))

    try:
        client = await _get_clickhouse_client(client_factory)
    except Exception as exc:
        _logger.warning("CH unavailable: %s", exc)
        return []

    sql = (
        "SELECT event_id, event_type, workflow_id, tenant_id, payload, "
        "created_at, duration_ms FROM workflow_audit "
        "WHERE workflow_id = %(workflow_id)s "
        "  AND event_type IN ('workflow.compensation_start', "
        "      'workflow.compensation_complete', "
        "      'workflow.compensation_fail') "
        "ORDER BY created_at DESC LIMIT %(limit)s"
    )
    try:
        result = await client.query(
            sql, parameters={"workflow_id": workflow_id, "limit": limit}
        )
    except Exception as exc:
        _logger.warning("CH query failed: %s", exc)
        return []

    records: list[SagaHistoryRecord] = []
    for row in getattr(result, "result_rows", []):
        try:
            payload = json.loads(row[4]) if row[4] else {}
        except TypeError, json.JSONDecodeError:
            payload = {}
        records.append(
            SagaHistoryRecord(
                event_id=row[0],
                event_type=row[1],
                workflow_id=row[2],
                tenant_id=row[3],
                payload=payload,
                created_at=row[5],
                duration_ms=row[6],
            )
        )
    return records


async def aggregate_saga_stats(
    *,
    tenant_id: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    client_factory: Any | None = None,
) -> dict[str, Any]:
    """Aggregated stats для page 19 (общая сводка)."""
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    to_dt = to_dt or _dt.now(UTC)
    from_dt = from_dt or (to_dt - _td(days=7))

    try:
        client = await _get_clickhouse_client(client_factory)
    except Exception as exc:
        _logger.warning("CH unavailable: %s", exc)
        return {"total_sagas": 0, "succeeded": 0, "failed": 0, "avg_duration_ms": 0.0}

    conditions = [
        "created_at >= %(from_dt)s",
        "created_at <= %(to_dt)s",
        "event_type IN ('workflow.compensation_complete', "
        "  'workflow.compensation_fail')",
    ]
    params: dict[str, Any] = {"from_dt": from_dt, "to_dt": to_dt}
    if tenant_id:
        conditions.append("tenant_id = %(tenant_id)s")
        params["tenant_id"] = tenant_id

    sql = (
        "SELECT countIf(event_type='workflow.compensation_complete') AS succeeded, "  # noqa: S608  # internal query with controlled parameters
        "  countIf(event_type='workflow.compensation_fail') AS failed, "
        "  avg(duration_ms) AS avg_dur "
        f"FROM workflow_audit WHERE {' AND '.join(conditions)}"
    )

    try:
        result = await client.query(sql, parameters=params)
        row = result.result_rows[0] if getattr(result, "result_rows", None) else None
    except Exception as exc:
        _logger.warning("CH query failed: %s", exc)
        row = None

    if row is None:
        return {"total_sagas": 0, "succeeded": 0, "failed": 0, "avg_duration_ms": 0.0}

    succeeded = int(row[0] or 0)
    failed = int(row[1] or 0)
    avg_dur = float(row[2] or 0.0)
    return {
        "total_sagas": succeeded + failed,
        "succeeded": succeeded,
        "failed": failed,
        "avg_duration_ms": avg_dur,
    }
