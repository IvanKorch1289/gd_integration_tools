"""HITL REST API endpoints (Sprint 9 K3 W2).

Эндпоинты:

* ``GET /hitl/pending?tenant_id=...`` — список pending HITL signals.
* ``POST /hitl/{signal_id}/resolve`` — разрешить signal (approve/reject/info).
* ``GET /hitl/{signal_id}`` — детали одного signal.

Auth: JWT + tenant filtering (X-Tenant-ID); permission ``hitl.resolve``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.backend.services.workflows.hitl_service import (
    HitlAction,
    HitlService,
)

__all__ = ("router",)

router = APIRouter()


class HitlResolveRequest(BaseModel):
    """Тело POST /hitl/{signal_id}/resolve."""

    action: str = Field(..., description="approve | reject | request_info")
    resolved_by: str = Field(
        ..., min_length=1, description="Имя/UID оператора (для audit)"
    )
    comment: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


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
    request: Request,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Список pending HITL signals (опц. фильтр по tenant)."""
    svc = _service(request)
    items = await svc.list_pending(tenant_id=tenant_id)
    return {"items": [s.to_dict() for s in items], "count": len(items)}


@router.get("/{signal_id}", summary="Get HITL signal details")
async def get_signal(signal_id: str, request: Request) -> dict[str, Any]:
    svc = _service(request)
    signal = await svc.get(signal_id)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"HITL signal {signal_id!r} not found",
        )
    return signal.to_dict()


@router.post("/{signal_id}/resolve", summary="Resolve HITL signal")
async def resolve_signal(
    signal_id: str,
    body: HitlResolveRequest,
    request: Request,
) -> dict[str, Any]:
    """Approve / reject / request_info → signal_workflow + store.mark_resolved."""
    if body.action not in HitlAction.all():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid action {body.action!r}; allowed: {HitlAction.all()}"
            ),
        )
    svc = _service(request)
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
