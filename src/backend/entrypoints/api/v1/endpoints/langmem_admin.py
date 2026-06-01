"""LangMem admin endpoints (Wave D.6).

* ``POST /admin/langmem/consolidate`` — manual trigger consolidate().
* ``GET /admin/langmem/stats`` — counts по типам памяти.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.backend.entrypoints.api.dependencies.auth_selector import (
    AuthMethod,
    require_auth,
)

__all__ = ("router",)

router = APIRouter()


@router.post(
    "/langmem/consolidate",
    summary="Запустить consolidate() episodic → semantic (D.6)",
    dependencies=[Depends(require_auth([AuthMethod.API_KEY, AuthMethod.JWT]))],
)
async def langmem_consolidate(
    since: str | None = Query(default=None, description="ISO-метка cutoff"),
    batch_size: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """Запускает LLM-summarization consolidate()."""
    from src.backend.services.ai.langmem_service import (
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
    dependencies=[Depends(require_auth([AuthMethod.API_KEY, AuthMethod.JWT]))],
)
async def langmem_stats() -> dict[str, Any]:
    """Возвращает counts по episodic / procedural."""
    from src.backend.services.ai.langmem_service import (
        LangMemDisabled,
        get_langmem_service,
    )

    try:
        return await get_langmem_service().stats()
    except LangMemDisabled as exc:
        raise HTTPException(503, detail=str(exc)) from exc
