"""Admin REST для управления :class:`ResilienceProfile` (S13 K2 W5).

Endpoints:

* ``GET /admin/resilience-profiles`` — список профилей (global + per-tenant).
* ``GET /admin/resilience-profiles/{name}`` — current effective.
* ``PUT /admin/resilience-profiles/{name}`` — upsert (global или per-tenant).
* ``DELETE /admin/resilience-profiles/{name}`` — удаление.

Защищён ``require_admin((AdminRole.OPERATOR, AdminRole.SUPER_ADMIN))``.
Tenant-scope определяется через query-параметр ``tenant_id`` (опциональный).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.backend.core.auth.admin_roles import AdminRole, require_admin
from src.backend.core.di.dependencies import get_resilience_profile_store
from src.backend.core.resilience.resilience_profile import (
    BulkheadPolicy,
    CircuitBreakerPolicy,
    RateLimitPolicy,
    ResilienceProfile,
    ResilienceProfileStore,
    RetryPolicySpec,
)

__all__ = ("router",)

router = APIRouter(prefix="/admin/resilience-profiles", tags=["Admin / Resilience"])


class RetryPolicyIn(BaseModel):
    max_attempts: int = Field(3, ge=1, le=10)
    base_delay_ms: int = Field(100, ge=10, le=5000)
    max_delay_ms: int = Field(5000, ge=100, le=60000)
    exp_base: float = Field(2.0, ge=1.1, le=3.0)
    jitter: float = Field(0.1, ge=0.0, le=1.0)


class CircuitBreakerIn(BaseModel):
    failure_threshold: int = Field(5, ge=3, le=50)
    recovery_timeout_s: int = Field(30, ge=10, le=3600)
    half_open_max_calls: int = Field(3, ge=1, le=10)


class RateLimitIn(BaseModel):
    rps: int = Field(100, ge=1, le=10000)
    burst: int = Field(20, ge=1, le=100)


class BulkheadIn(BaseModel):
    high_watermark: int = Field(100, ge=10, le=1000)
    low_watermark: int = Field(50, ge=5, le=500)


class ResilienceProfileIn(BaseModel):
    retry: RetryPolicyIn = RetryPolicyIn()
    circuit_breaker: CircuitBreakerIn = CircuitBreakerIn()
    rate_limit: RateLimitIn | None = None
    bulkhead: BulkheadIn | None = None


def _profile_from_payload(name: str, payload: ResilienceProfileIn) -> ResilienceProfile:
    return ResilienceProfile(
        name=name,
        retry=RetryPolicySpec(**payload.retry.model_dump()),
        circuit_breaker=CircuitBreakerPolicy(**payload.circuit_breaker.model_dump()),
        rate_limit=(
            RateLimitPolicy(**payload.rate_limit.model_dump())
            if payload.rate_limit
            else None
        ),
        bulkhead=(
            BulkheadPolicy(**payload.bulkhead.model_dump())
            if payload.bulkhead
            else None
        ),
    )


@router.get(
    "",
    dependencies=[Depends(require_admin((AdminRole.OPERATOR, AdminRole.READ_ONLY)))],
    summary="Список resilience profiles (global + per-tenant)",
    description=(
        "Возвращает список ResilienceProfile (retry + CB + rate_limit + "
        "bulkhead политики). Опциональный query param tenant_id: если задан — "
        "только per-tenant профили, иначе — global. Используется Admin UI "
        "для observability resilience configuration."
    ),
    tags=["Admin / Resilience"],
    responses={
        200: {"description": "Список profile dicts."},
        401: {"description": "Missing/invalid admin credentials."},
        403: {"description": "User lacks Operator/Read-Only role."},
    },
)
async def list_profiles(
    tenant_id: str | None = None,
    store: ResilienceProfileStore = Depends(get_resilience_profile_store),
) -> dict[str, Any]:
    profiles = await store.list(tenant_id=tenant_id)
    return {"profiles": [p.to_dict() for p in profiles]}


@router.get(
    "/{name}",
    dependencies=[Depends(require_admin((AdminRole.OPERATOR, AdminRole.READ_ONLY)))],
    summary="Получить effective resilience profile по имени",
    description=(
        "Возвращает effective ResilienceProfile: если есть per-tenant override "
        "(tenant_id query param), возвращает его, иначе — global. "
        "404 если profile не найден ни в одном scope."
    ),
    tags=["Admin / Resilience"],
    responses={
        200: {"description": "Profile dict."},
        404: {"description": "Profile не найден."},
    },
)
async def get_profile(
    name: str,
    tenant_id: str | None = None,
    store: ResilienceProfileStore = Depends(get_resilience_profile_store),
) -> dict[str, Any]:
    profile = await store.get(name, tenant_id=tenant_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"resilience profile '{name}' not found",
        )
    return profile.to_dict()


@router.put(
    "/{name}",
    dependencies=[Depends(require_admin((AdminRole.OPERATOR,)))],
    summary="Upsert resilience profile (global или per-tenant)",
    description=(
        "Создаёт или обновляет ResilienceProfile. Опциональный query param "
        "tenant_id: если задан — per-tenant override, иначе — global. "
        "Validation через pydantic (max_attempts 1-10, base_delay_ms 10-5000, etc.). "
        "Требует Operator role."
    ),
    tags=["Admin / Resilience"],
    responses={
        200: {"description": "Saved profile dict."},
        403: {"description": "User lacks Operator role."},
        422: {"description": "Validation error (invalid retry/CB parameters)."},
    },
)
async def upsert_profile(
    name: str,
    payload: ResilienceProfileIn,
    tenant_id: str | None = None,
    store: ResilienceProfileStore = Depends(get_resilience_profile_store),
) -> dict[str, Any]:
    profile = _profile_from_payload(name, payload)
    saved = await store.upsert(profile, tenant_id=tenant_id)
    return saved.to_dict()


@router.delete(
    "/{name}",
    dependencies=[Depends(require_admin((AdminRole.OPERATOR,)))],
    summary="Удалить resilience profile (global или per-tenant)",
    description=(
        "Удаляет ResilienceProfile. Опциональный tenant_id для per-tenant "
        "scope. Возвращает {\"deleted\": true/false} в зависимости от "
        "существования. Требует Operator role."
    ),
    tags=["Admin / Resilience"],
    responses={
        200: {"description": "{\"deleted\": bool}."},
        403: {"description": "User lacks Operator role."},
    },
)
async def delete_profile(
    name: str,
    tenant_id: str | None = None,
    store: ResilienceProfileStore = Depends(get_resilience_profile_store),
) -> dict[str, bool]:
    deleted = await store.delete(name, tenant_id=tenant_id)
    return {"deleted": deleted}
