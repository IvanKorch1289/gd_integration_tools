"""LangMem admin endpoints (Wave D.6).

* ``POST /admin/langmem/consolidate`` — manual trigger consolidate().
* ``GET /admin/langmem/stats`` — counts по типам памяти.

P0 (cycle 6, production-grade plan): ранее endpoint использовал только
``require_auth`` (любой authenticated principal). После добавления
``require_admin(OPERATOR, SUPER_ADMIN)`` LangMem consolidation требует
admin role. API key holder по-прежнему получает admin role через
``APIKeyMiddleware`` (configurable в Cycle 7), но теперь доступ явно
требуется на endpoint level.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.backend.core.auth.admin_roles import AdminRole, require_admin

__all__ = ("router",)

router = APIRouter(
    dependencies=[Depends(require_admin((AdminRole.OPERATOR, AdminRole.SUPER_ADMIN)))]
)


@router.post(
    "/langmem/consolidate",
    summary="Запустить consolidate() episodic → semantic (D.6)",
)
async def langmem_consolidate(
    since: str | None = Query(default=None, description="ISO-метка cutoff"),
    batch_size: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """Запускает LLM-summarization consolidate()."""
    from src.backend.services.ai.memory.langmem_service import (
        LangMemDisabled,
        get_langmem_service,
    )

    cutoff: datetime | None = None
    if since:
        try:
            cutoff = datetime.fromisoformat(since)
        except ValueError as exc:
            raise HTTPException(400, detail=f"Invalid ISO datetime: {exc}") from exc

    service = get_langmem_service()
    try:
        return await service.consolidate(since=cutoff, batch_size=batch_size)
    except LangMemDisabled as exc:
        raise HTTPException(503, detail=str(exc)) from exc


@router.get(
    "/langmem/stats",
    summary="Статистика памяти LangMem (D.6)",
)
async def langmem_stats() -> dict[str, Any]:
    """Возвращает counts по episodic / procedural."""
    from src.backend.services.ai.memory.langmem_service import (
        LangMemDisabled,
        get_langmem_service,
    )

    try:
        return await get_langmem_service().stats()
    except LangMemDisabled as exc:
        raise HTTPException(503, detail=str(exc)) from exc
