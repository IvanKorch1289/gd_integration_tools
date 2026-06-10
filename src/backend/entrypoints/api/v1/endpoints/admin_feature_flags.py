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

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.backend.core.config.features import feature_flags
from src.backend.core.feature_flags.openfeature_provider import (
    FlagsmithBackend,
    get_openfeature_backend,
)
from src.backend.core.feature_flags.runtime_overrides import (
    FeatureFlagChange,
    get_runtime_overrides,
)
from src.backend.core.logging import get_logger
from src.backend.services.audit import get_unified_audit_service

__all__ = ("router",)

_logger = get_logger("entrypoints.api.v1.admin.feature_flags")

router = APIRouter()


async def _maybe_publish(request: Request, change: FeatureFlagChange) -> None:
    """Опубликовать FeatureFlagChange через Redis broadcaster, если активен.

    Sprint 17 K5 W1 (D9). Broadcaster хранится в ``app.state`` после
    lifespan startup при ``tenant_feature_flag_ui=True``. При отсутствии —
    no-op (single-replica режим).
    """
    bcast = getattr(request.app.state, "feature_flag_broadcaster", None)
    if bcast is None:
        return
    try:
        await bcast.publish(change)
    except Exception as exc:
        _logger.warning(
            "feature_flag.broadcast.publish_skipped: %s",
            exc,
            extra={"flag": change.flag, "tenant_id": change.tenant_id},
        )


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
        description=("Опц. для per-tenant override. ``None`` — global override."),
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


@router.get("/feature-flags/backend-status", tags=["Admin · Feature Flags"])
async def backend_status() -> dict[str, Any]:
    """Статус активного feature-flag backend'а.

    Возвращает имя backend'а (``in-memory`` / ``flagsmith``),
    признак готовности и количество флагов в static-реестре.
    """
    backend = get_openfeature_backend()
    backend_name = "flagsmith" if isinstance(backend, FlagsmithBackend) else "in-memory"
    ready = True
    if isinstance(backend, FlagsmithBackend):
        ready = getattr(backend, "_provider", None) is not None

    flag_count = len(type(feature_flags).model_fields)
    return {"backend": backend_name, "ready": ready, "flag_count": flag_count}


@router.get("/feature-flags", tags=["Admin · Feature Flags"])
async def list_overrides() -> dict[str, Any]:
    """Снимок всех runtime overrides."""
    return get_runtime_overrides().list_overrides()


@router.put("/feature-flags/{flag}", tags=["Admin · Feature Flags"])
async def set_override(
    flag: str, body: SetOverrideRequest, request: Request
) -> OverrideResponse:
    """Установить runtime override для feature-flag.

    Эмитирует ``feature.toggled`` audit-event через unified
    :class:`AuditService` (см. ``services/audit/audit_service.py``)
    и публикует change через Redis pub/sub broadcaster (S17 K5 W1 D9),
    если ``tenant_feature_flag_ui=True`` и broadcaster активен.
    """
    overrides = get_runtime_overrides()
    change = overrides.set(flag, body.value, tenant_id=body.tenant_id, actor=body.actor)

    await get_unified_audit_service().emit(
        event="feature.toggled",
        actor=body.actor,
        resource=f"feature_flag/{flag}",
        action="set",
        outcome="success",
        tenant_id=body.tenant_id,
        details={"old_value": change.old_value, "new_value": change.new_value},
    )
    await _maybe_publish(request, change)
    return _to_response(change)


@router.delete("/feature-flags/{flag}", tags=["Admin · Feature Flags"])
async def clear_override(
    flag: str,
    request: Request,
    tenant_id: str | None = Query(default=None),
    actor: str = Query(default="system"),
) -> OverrideResponse:
    """Снять runtime override — flag вернётся к static-default.

    Также публикует clear-change через Redis broadcaster (S17 K5 W1 D9)
    для multi-replica propagation, если broadcaster активен.
    """
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
    await _maybe_publish(request, change)
    return _to_response(change)
