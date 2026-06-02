"""Admin workflow_audit endpoints — Sprint 12 K1 W1.

Endpoints (mount /api/v1/admin/workflow-audit):

* ``GET /inventory`` — count by event_type за последние 24h.
  Используется в Streamlit page 66 / 50 для health-overview audit-trail.
* ``GET /events`` — query events с фильтрами
  (workflow_id, tenant_id, event_type, from, to, limit).

Авторизация: эндпоинты монтируются под ``/admin`` — защищены
RBAC-middleware (admin role).

Безопасность:
    * limit clamped до [1, 1000];
    * from/to принимаются как ISO-8601 UTC;
    * payload возвращается as-is (JSON string), фронтенд парсит сам.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

__all__ = ("router",)

router = APIRouter(prefix="/admin/workflow-audit", tags=["admin", "workflow"])


_ALLOWED_EVENT_TYPES = frozenset(
    {
        "workflow.start",
        "workflow.signal",
        "workflow.cancel",
        "workflow.complete",
        "workflow.fail",
        "workflow.query",
        "workflow.compensation_start",
        "workflow.compensation_complete",
        "workflow.compensation_fail",
        "hitl.approved",
        "hitl.rejected",
        "hitl.requested_info",
        "activity.start",
        "activity.complete",
    }
)


class WorkflowAuditEventResponse(BaseModel):
    """Одна строка из таблицы ``workflow_audit``."""

    event_id: str
    event_type: str
    workflow_id: str
    tenant_id: str | None = None
    payload: str
    trace_id: str | None = None
    created_at: datetime
    actor: str | None = None
    duration_ms: int | None = None
    parent_workflow_id: str | None = None


class WorkflowAuditInventoryResponse(BaseModel):
    """Breakdown по event_type за окно."""

    window_hours: int
    total_events: int
    breakdown: dict[str, int] = Field(
        default_factory=dict, description="event_type → count"
    )


async def _get_clickhouse_client() -> Any:
    """Создаёт async ClickHouse-клиент через ``clickhouse_connect``."""
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


@router.get(
    "/inventory",
    response_model=WorkflowAuditInventoryResponse,
    summary="Breakdown workflow_audit по event_type за N часов",
)
async def get_audit_inventory(
    window_hours: int = Query(24, ge=1, le=720),
) -> WorkflowAuditInventoryResponse:
    """Возвращает count по event_type за указанное окно (default 24h, max 30d).

    Использует ClickHouse aggregate ``count() GROUP BY event_type``;
    скан ограничен партициями за период через ``WHERE created_at >= ...``.
    """
    try:
        client = await _get_clickhouse_client()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ClickHouse unavailable: {exc}",
        ) from exc

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    try:
        result = await client.query(
            "SELECT event_type, count() AS cnt FROM workflow_audit "
            "WHERE created_at >= %(cutoff)s "
            "GROUP BY event_type ORDER BY cnt DESC",
            parameters={"cutoff": cutoff},
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ClickHouse query failed: {exc}",
        ) from exc

    breakdown: dict[str, int] = {}
    total = 0
    for row in getattr(result, "result_rows", []):
        event_type, cnt = row[0], int(row[1])
        breakdown[event_type] = cnt
        total += cnt

    return WorkflowAuditInventoryResponse(
        window_hours=window_hours, total_events=total, breakdown=breakdown
    )


@router.get(
    "/events",
    response_model=list[WorkflowAuditEventResponse],
    summary="Query workflow_audit events с фильтрами",
)
async def get_audit_events(
    workflow_id: str | None = Query(None),
    tenant_id: str | None = Query(None),
    event_type: str | None = Query(None, description="Один из allowed event_types."),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> list[WorkflowAuditEventResponse]:
    """Возвращает события из ``workflow_audit`` с фильтрами.

    Default ``to = now()``, ``from = to - 7d`` если не указаны.
    """
    if event_type is not None and event_type not in _ALLOWED_EVENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"event_type {event_type!r} не входит в allowlist. "
                f"Допустимо: {sorted(_ALLOWED_EVENT_TYPES)}."
            ),
        )

    to_dt = to or datetime.now(timezone.utc)
    from_dt = from_ or (to_dt - timedelta(days=7))

    conditions = ["created_at >= %(from_)s", "created_at <= %(to)s"]
    params: dict[str, Any] = {"from_": from_dt, "to": to_dt, "limit": limit}
    if workflow_id:
        conditions.append("workflow_id = %(workflow_id)s")
        params["workflow_id"] = workflow_id
    if tenant_id:
        conditions.append("tenant_id = %(tenant_id)s")
        params["tenant_id"] = tenant_id
    if event_type:
        conditions.append("event_type = %(event_type)s")
        params["event_type"] = event_type

    sql = (  # noqa: S608
        "SELECT event_id, event_type, workflow_id, tenant_id, payload, "  # noqa: S608
        "trace_id, created_at, actor, duration_ms, parent_workflow_id "
        f"FROM workflow_audit WHERE {' AND '.join(conditions)} "
        "ORDER BY created_at DESC LIMIT %(limit)s"
    )

    try:
        client = await _get_clickhouse_client()
        result = await client.query(sql, parameters=params)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ClickHouse unavailable: {exc}",
        ) from exc

    events: list[WorkflowAuditEventResponse] = []
    for row in getattr(result, "result_rows", []):
        events.append(
            WorkflowAuditEventResponse(
                event_id=row[0],
                event_type=row[1],
                workflow_id=row[2],
                tenant_id=row[3],
                payload=row[4],
                trace_id=row[5],
                created_at=row[6],
                actor=row[7],
                duration_ms=row[8],
                parent_workflow_id=row[9],
            )
        )
    return events
