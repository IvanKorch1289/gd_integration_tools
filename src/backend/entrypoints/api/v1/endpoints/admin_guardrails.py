"""Admin REST API для метрик guardrails (ADR-0432).

Endpoints (под ``/api/v1/admin``):

* ``GET /guardrails-metrics`` — агрегаты по тенантам (проверки, блокировки,
  redact, false-positive rate);
* ``POST /guardrails-metrics/{tenant_id}/false-positive`` — ручная отметка
  false-positive (снижает FP-rate в дашборде).

Авторизация: admin-роль (``OPERATOR`` / ``SUPER_ADMIN``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.backend.core.auth.admin_roles import AdminRole, require_admin
from src.backend.core.logging import get_logger

__all__ = ("router",)

logger = get_logger("entrypoints.admin_guardrails")

_ADMIN_GUARD = Depends(require_admin((AdminRole.OPERATOR, AdminRole.SUPER_ADMIN)))

router = APIRouter(dependencies=[_ADMIN_GUARD])


@router.get(
    "/guardrails-metrics",
    summary="Метрики guardrails по тенантам",
    description=(
        "Агрегаты AI-Safety guardrails: всего проверок, allow/block/redact, "
        "false-positive rate. Пустой список — guardrails ещё не вызывались."
    ),
    tags=["Admin · Guardrails"],
    responses={200: {"description": "Список агрегатов по тенантам."}},
)
async def list_guardrails_metrics() -> list[dict[str, Any]]:
    """Метрики guardrails по тенантам."""
    from src.backend.core.di.providers.guardrails import (
        get_guardrails_metrics_service_provider,
    )

    service = get_guardrails_metrics_service_provider()
    return [item.to_dict() for item in await service.list_all()]


@router.post(
    "/guardrails-metrics/{tenant_id}/false-positive",
    summary="Отметить false-positive",
    description=(
        "Ручная отметка false-positive: уменьшает FP-rate в дашборде "
        "(используется при ручном ревью блокировок)."
    ),
    tags=["Admin · Guardrails"],
    responses={
        200: {"description": "Отметка принята."},
        404: {"description": "Тенант не найден в метриках."},
    },
)
async def mark_guardrails_false_positive(
    tenant_id: str, count: int = Query(default=1, ge=1, le=1000)
) -> dict[str, Any]:
    """Отметить ``count`` false-positive для тенанта."""
    from src.backend.core.di.providers.guardrails import (
        get_guardrails_metrics_service_provider,
    )

    service = get_guardrails_metrics_service_provider()
    metrics = await service.snapshot(tenant_id)
    if metrics.total == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Нет метрик guardrails для tenant_id={tenant_id!r}",
        )
    await service.mark_false_positive(tenant_id=tenant_id, count=count)
    updated = await service.snapshot(tenant_id)
    return {"tenant_id": tenant_id, "count": count, "metrics": updated.to_dict()}
