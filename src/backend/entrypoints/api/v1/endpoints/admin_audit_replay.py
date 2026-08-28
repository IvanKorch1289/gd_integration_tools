r"""Admin audit-replay endpoint (S34 W1, Phase C close-out).

``GET /api/v1/admin/audit/capability`` — последние N записей из Redis
audit stream ``audit:events``. Используется UI page 34 (DSL Отладчик →
"Аудит Replay") для drill-down на конкретный request.

Data source: Redis stream (per :func:`services.audit.replay_query.list_audit_records`).
NOT equivalent to ``/admin/workflow-audit/events`` (ClickHouse audit table,
different schema).

Sprint 34 W1 (S34): closes Phase C HTTP-migration for ``list_audit_records``
facade symbol. Параллельно с commit `b348392b` который closed
``list_recent_trace_events`` (dead code).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from src.backend.core.auth.admin_roles import AdminRole, require_admin

__all__ = ("router",)


# S202 audit fix: require admin role для read-only audit endpoint.
_ADMIN_GUARD_READ = Depends(
    require_admin((AdminRole.OPERATOR, AdminRole.READ_ONLY, AdminRole.SUPER_ADMIN))
)

router = APIRouter(dependencies=[_ADMIN_GUARD_READ])


class AuditRecordResponse(BaseModel):
    """Одна запись из audit stream ``audit:events``.

    Schema: shape Redis stream entry. Поля best-effort (Redis stream
    может иметь произвольные keys → defensive ``.get()``).
    """

    record_id: str = Field(description="Stream ID записи (e.g. ``1700000000000-0``).")
    timestamp: str | None = Field(default=None, description="ISO-8601 UTC timestamp.")
    method: str | None = Field(default=None, description="HTTP method (GET/POST/...).")
    path: str | None = Field(default=None, description="HTTP path запроса.")
    status_code: int | None = Field(
        default=None, description="HTTP status code ответа."
    )
    duration_ms: float | None = Field(
        default=None, description="Request duration в ms."
    )
    tenant_id: str | None = Field(
        default=None, description="Tenant ID из auth context."
    )
    user_id: str | None = Field(default=None, description="User ID из auth context.")
    body: dict[str, Any] | None = Field(
        default=None, description="Request body (JSON-decoded)."
    )


def _to_response(record: dict[str, Any]) -> AuditRecordResponse:
    """Defensive mapper: Redis stream entry → AuditRecordResponse."""
    return AuditRecordResponse(
        record_id=record.get("id") or record.get("record_id") or "",
        timestamp=record.get("timestamp"),
        method=record.get("method"),
        path=record.get("path"),
        status_code=record.get("status_code"),
        duration_ms=record.get("duration_ms"),
        tenant_id=record.get("tenant_id"),
        user_id=record.get("user_id"),
        body=record.get("body") if isinstance(record.get("body"), dict) else None,
    )


@router.get(
    "/audit/capability",
    response_model=list[AuditRecordResponse],
    summary="Audit-replay records (last N из Redis stream)",
    description=(
        "Возвращает последние N записей из audit stream ``audit:events`` "
        "для drill-down на конкретный HTTP request в UI Replay. "
        "Read-only endpoint, admin role."
    ),
    tags=["Admin · Audit Replay"],
    responses={200: {"description": "Список audit records (может быть пустым)."}},
)
async def list_audit_records_endpoint(
    count: int = Query(
        default=100, ge=1, le=1000, description="Максимум записей (1..1000)."
    ),
    start_id: str = Query(
        default="-", description="Stream ID начала чтения ('-' = с начала)."
    ),
) -> list[AuditRecordResponse]:
    """Возвращает последние N записей из Redis audit stream."""
    from src.backend.services.audit.replay_query import list_audit_records

    records = await list_audit_records(count=count, start_id=start_id)
    return [_to_response(r) for r in records]
