from __future__ import annotations

"""HITL REST API endpoints (Sprint 9 K3 W2).

Эндпоинты:

* ``GET /hitl/pending?tenant_id=...`` — список pending HITL signals.
* ``POST /hitl/{signal_id}/resolve`` — разрешить signal (approve/reject/info).
* ``GET /hitl/{signal_id}`` — детали одного signal.

Auth: JWT + tenant filtering (X-Tenant-ID); permission ``hitl.resolve``.

cycle-6/D-AUDIT-607: router fail-closed проверяет ``hitl.resolve``, а все
операции ограничены tenant из доверенного auth context.
"""


from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.backend.core.auth import AuthContext, extract_tenant_id
from src.backend.core.auth.auth_context_helpers import extract_user_permissions
from src.backend.services.workflows.hitl_service import HitlAction, HitlService

__all__ = ("router",)


def require_permission(permission: str) -> Callable[[Request], Awaitable[AuthContext]]:
    """Требует authentication context и указанное permission."""

    async def dependency(request: Request) -> AuthContext:
        auth: AuthContext | None = getattr(request.state, "auth", None)
        if auth is None:
            auth = getattr(request.state, "auth_context", None)
        if auth is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        if permission not in extract_user_permissions(auth):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission {permission!r} required",
            )
        return auth

    return dependency


router = APIRouter(dependencies=[Depends(require_permission("hitl.resolve"))])


class HitlResolveRequest(BaseModel):
    """Тело POST /hitl/{signal_id}/resolve."""

    action: str = Field(..., description="approve | reject | request_info")
    resolved_by: str = Field(
        ..., min_length=1, description="Имя/UID оператора (для audit)"
    )
    comment: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


def _request_tenant_id(request: Request) -> str:
    """Возвращает tenant из auth context, с middleware fallback."""
    auth = getattr(request.state, "auth", None) or getattr(
        request.state, "auth_context", None
    )
    tenant_id = extract_tenant_id(auth)
    if tenant_id is None:
        tenant_id = getattr(request.state, "tenant_id", None)
    if not isinstance(tenant_id, str) or not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Tenant context required"
        )
    return tenant_id


def _ensure_tenant(request: Request, signal_tenant_id: str) -> str:
    """Проверяет, что signal принадлежит tenant текущего запроса."""
    tenant_id = _request_tenant_id(request)
    if signal_tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="HITL signal belongs to another tenant",
        )
    return tenant_id


def _service(request: Request) -> HitlService:
    svc = getattr(request.app.state, "hitl_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="HITL service not configured",
        )
    return svc


@router.get("/pending", summary="List pending HITL signals")
async def list_pending(
    request: Request, tenant_id: str | None = None
) -> dict[str, Any]:
    """Список pending HITL signals только текущего tenant."""
    current_tenant = _request_tenant_id(request)
    if tenant_id is not None and tenant_id != current_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another tenant"
        )
    svc = _service(request)
    items = await svc.list_pending(tenant_id=current_tenant)
    return {"items": [s.to_dict() for s in items], "count": len(items)}


# ──────────────────────── Sprint 12 K5 W2: History ─────────────
@router.get("/history", summary="HITL decisions history (S12 K5 W2)")
async def hitl_history(
    request: Request,
    tenant_id: str | None = None,
    action: str | None = None,
    operator: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Historical decisions текущего tenant из workflow_audit.

    Sprint 12 K5 W2 — page 72 "History" tab.
    """
    from src.backend.services.workflows.hitl_history import HitlHistoryService

    current_tenant = _request_tenant_id(request)
    if tenant_id is not None and tenant_id != current_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another tenant"
        )
    service = HitlHistoryService()
    records = await service.get_history(
        tenant_id=current_tenant, action=action, operator=operator, limit=limit
    )
    return {
        "items": [
            {
                "signal_id": r.signal_id,
                "workflow_id": r.workflow_id,
                "tenant_id": r.tenant_id,
                "action": r.action,
                "operator": r.operator,
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                "duration_ms": r.duration_ms,
                "comment": r.comment,
            }
            for r in records
        ],
        "count": len(records),
    }


@router.get("/{signal_id}", summary="Get HITL signal details")
async def get_signal(signal_id: str, request: Request) -> dict[str, Any]:
    """Возвращает детали HITL-signal только для tenant запроса."""
    svc = _service(request)
    signal = await svc.get(signal_id)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"HITL signal {signal_id!r} not found",
        )
    _ensure_tenant(request, signal.tenant_id)
    return signal.to_dict()


@router.post("/{signal_id}/resolve", summary="Resolve HITL signal")
async def resolve_signal(
    signal_id: str, body: HitlResolveRequest, request: Request
) -> dict[str, Any]:
    """Approve / reject / request_info для tenant текущего запроса."""
    if body.action not in HitlAction.all():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"Invalid action {body.action!r}; allowed: {HitlAction.all()}"),
        )
    svc = _service(request)
    existing = await svc.get(signal_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"HITL signal {signal_id!r} not found",
        )
    _ensure_tenant(request, existing.tenant_id)
    try:
        signal = await svc.resolve(
            signal_id=signal_id,
            action=body.action,
            resolved_by=body.resolved_by,
            payload={"comment": body.comment, **body.extra},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return signal.to_dict()
