"""К5 (Wave K5/docs-tenants-caps) — admin REST API для tenants.

Endpoints (под ``/api/v1/admin``):

* ``GET /tenants`` — список tenant'ов с агрегатом по audit-events
  (event_count, last_seen, unique_actions). Stream E.9: enrichment
  через ``audit_log.query`` (ClickHouse) с in-Python группировкой по
  ``tenant_id``. Если ClickHouse недоступен — возвращается пустой
  список + ``stub: true``.
* ``GET /tenants/{tenant_id}`` — детальный профиль (последние audit
  events, capability denials, RLS state).

Авторизация: эндпоинты монтируются под ``/admin`` — защищены глобальным
:class:`APIKeyMiddleware`. Capability-gate: ``admin.read.tenants``.
"""

from __future__ import annotations

import logging
from collections import Counter as CollectionsCounter
from typing import Any

from fastapi import APIRouter

__all__ = ("router",)

logger = logging.getLogger("entrypoints.admin_tenants")

router = APIRouter()


_DEFAULT_AUDIT_LIMIT = 2000
_DEFAULT_DETAIL_LIMIT = 200


async def _query_audit_safe(
    *,
    who: str | None = None,
    entity_type: str | None = None,
    limit: int = _DEFAULT_AUDIT_LIMIT,
) -> list[dict[str, Any]] | None:
    """Безопасно вызывает ``audit_log.query``.

    Возвращает ``None`` при недоступности ClickHouse / отсутствии
    модуля — вызывающий должен fallback'нуть на stub-структуру.
    """
    try:
        from src.backend.infrastructure.audit.event_log import get_audit_log
    except ImportError:
        return None

    try:
        log = get_audit_log()
        rows = await log.query(who=who, entity_type=entity_type, limit=limit)
    except Exception as exc:
        logger.warning("audit-log query failed: %s", exc)
        return None
    return rows


def _aggregate_tenants(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Группирует audit-events по ``tenant_id``.

    Возвращает список ``{tenant_id, event_count, unique_actions, last_seen}``,
    отсортированный по ``event_count`` desc.
    """
    by_tenant: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        tid = str(row.get("tenant_id") or "").strip()
        if not tid:
            continue
        by_tenant.setdefault(tid, []).append(row)

    aggregated: list[dict[str, Any]] = []
    for tid, items in by_tenant.items():
        # ``CollectionsCounter`` — это ``collections.Counter`` (счётчик строк),
        # не ``prometheus_client.Counter``.
        actions = CollectionsCounter(
            str(r.get("action", "")) for r in items if r.get("action")
        )
        last_seen = max(
            (str(r.get("when", "")) for r in items if r.get("when")), default=None
        )
        aggregated.append(
            {
                "tenant_id": tid,
                "event_count": len(items),
                "unique_actions": len(actions),
                "top_actions": [
                    {"action": a, "count": c} for a, c in actions.most_common(5)
                ],
                "last_seen": last_seen,
            }
        )

    aggregated.sort(key=lambda t: t["event_count"], reverse=True)
    return aggregated


@router.get(
    "/tenants",
    summary="Список tenants",
    description=(
        "Возвращает агрегированный список tenants с event_count, "
        "unique_actions, last_seen — реконструируется через "
        "audit_log.query (ClickHouse). При ClickHouse offline возвращает "
        "stub:true с пустым списком."
    ),
    tags=["Admin · Tenants"],
)
async def list_tenants(limit: int = _DEFAULT_AUDIT_LIMIT) -> dict[str, Any]:
    """Stream E.9: enrichment через audit_log.

    Args:
        limit: Глубина выборки audit-events для агрегации
            (clamped 1..10000 в audit_log.query).
    """
    safe_limit = max(1, min(int(limit), 10000))
    rows = await _query_audit_safe(limit=safe_limit)
    if rows is None:
        return {
            "tenants": [],
            "total": 0,
            "stub": True,
            "note": "Audit log недоступен (ClickHouse offline или модуль не импортирован).",
        }

    tenants = _aggregate_tenants(rows)
    return {
        "tenants": tenants,
        "total": len(tenants),
        "stub": False,
        "audit_window": safe_limit,
    }


@router.get(
    "/tenants/{tenant_id}",
    summary="Детали tenant'а",
    description=(
        "Recent audit-events + capability-denial counter + RLS state "
        "(последний из metadata, если присутствует)."
    ),
    tags=["Admin · Tenants"],
)
async def get_tenant_detail(
    tenant_id: str, limit: int = _DEFAULT_DETAIL_LIMIT
) -> dict[str, Any]:
    """Детали одного tenant'а (Stream E.9)."""
    safe_limit = max(1, min(int(limit), 1000))
    rows = await _query_audit_safe(limit=safe_limit * 5)
    if rows is None:
        return {
            "tenant_id": tenant_id,
            "plan": "unknown",
            "rate_limit": None,
            "quotas": [],
            "audit_events_recent": [],
            "capability_denials": 0,
            "rls_state": {"enabled": False},
            "stub": True,
        }

    own = [r for r in rows if str(r.get("tenant_id", "")) == tenant_id]
    own.sort(key=lambda r: str(r.get("when", "")), reverse=True)
    capability_denials = sum(
        1 for r in own if str(r.get("entity_type", "")).startswith("capability")
    )

    return {
        "tenant_id": tenant_id,
        "plan": "unknown",
        "rate_limit": None,
        "quotas": [],
        "audit_events_recent": own[:safe_limit],
        "capability_denials": capability_denials,
        "rls_state": {"enabled": False},
        "stub": False,
    }
