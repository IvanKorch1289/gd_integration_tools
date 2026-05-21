"""Admin endpoints для runtime управления feature-flags (Sprint 16 Wave 9, CP-15).

Эндпоинты:
    * ``GET /admin/feature-flags`` — снимок всех runtime overrides
      (global + per-tenant).
    * ``PUT /admin/feature-flags/{flag}`` — установить runtime override
      (опц. для конкретного tenant). Все изменения аудируются через
      :class:`AuditService.emit("feature.toggled", ...)`.
    * ``DELETE /admin/feature-flags/{flag}`` — снять runtime override.

Multi-replica propagation (carryover B-6 finale): сейчас работает только
per-process. Подключение Redis pub/sub channel ``feature-flags:toggle``
для propagation между репликами k8s — отдельный wave.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.backend.core.feature_flags.runtime_overrides import (
    FeatureFlagChange,
    get_runtime_overrides,
)
from src.backend.services.audit import get_unified_audit_service

__all__ = ("router",)

router = APIRouter()


class SetOverrideRequest(BaseModel):
    """Payload для установки runtime override flag'а."""

    value: Any = Field(
        ...,
        description=(
            "Значение override. Для boolean-flags используется bool; "
            "string/integer/object — соответствующий тип."
        ),
    )
    tenant_id: str | None = Field(
        default=None,
        description=(
            "Опц. для per-tenant override. ``None`` — global override."
        ),
    )
    actor: str = Field(
        default="system",
        description="Идентификатор инициатора (``user:<id>`` / ``system``).",
    )


class OverrideResponse(BaseModel):
    """Ответ на set/clear с детализацией изменения."""

    flag: str
    tenant_id: str | None
    old_value: Any
    new_value: Any
    actor: str


def _to_response(change: FeatureFlagChange) -> OverrideResponse:
    return OverrideResponse(
        flag=change.flag,
        tenant_id=change.tenant_id,
        old_value=change.old_value,
        new_value=change.new_value,
        actor=change.actor,
    )


@router.get("/feature-flags", tags=["Admin · Feature Flags"])
async def list_overrides() -> dict[str, Any]:
    """Снимок всех runtime overrides."""
    return get_runtime_overrides().list_overrides()


@router.put("/feature-flags/{flag}", tags=["Admin · Feature Flags"])
async def set_override(
    flag: str, body: SetOverrideRequest
) -> OverrideResponse:
    """Установить runtime override для feature-flag.

    Эмитирует ``feature.toggled`` audit-event через unified
    :class:`AuditService` (см. ``services/audit/audit_service.py``).
    """
    overrides = get_runtime_overrides()
    change = overrides.set(
        flag, body.value, tenant_id=body.tenant_id, actor=body.actor
    )

    await get_unified_audit_service().emit(
        event="feature.toggled",
        actor=body.actor,
        resource=f"feature_flag/{flag}",
        action="set",
        outcome="success",
        tenant_id=body.tenant_id,
        details={
            "old_value": change.old_value,
            "new_value": change.new_value,
        },
    )
    return _to_response(change)


@router.delete("/feature-flags/{flag}", tags=["Admin · Feature Flags"])
async def clear_override(
    flag: str,
    tenant_id: str | None = Query(default=None),
    actor: str = Query(default="system"),
) -> OverrideResponse:
    """Снять runtime override — flag вернётся к static-default."""
    overrides = get_runtime_overrides()
    change = overrides.clear(flag, tenant_id=tenant_id)
    if change is None:
        raise HTTPException(
            status_code=404,
            detail=f"Override для flag={flag!r} tenant={tenant_id!r} не найден",
        )

    await get_unified_audit_service().emit(
        event="feature.toggled",
        actor=actor,
        resource=f"feature_flag/{flag}",
        action="clear",
        outcome="success",
        tenant_id=tenant_id,
        details={"old_value": change.old_value},
    )
    return _to_response(change)
