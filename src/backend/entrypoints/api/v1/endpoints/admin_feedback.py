"""Admin REST для AI Feedback dashboard (Sprint 11 K5 W2).

* ``GET /admin/feedback/training-runs`` — список последних training runs
  DSPy с метаданными.
* ``GET /admin/feedback/labeled-count`` — кол-во labeled feedback per
  tenant (для UI).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/admin/feedback", tags=["admin", "feedback"])


@router.get("/training-runs")
async def list_training_runs(limit: int = 10) -> dict[str, Any]:
    """Последние DSPy training runs (in-memory stub; storage TBD).

    В production runs хранятся в LangfusePromptStorage; пока возвращается
    пустой список — отображается заголовок «Нет завершённых runs».
    """
    return {"runs": [], "count": 0, "limit": limit}


@router.get("/labeled-count")
async def labeled_count(tenant_id: str | None = None) -> dict[str, Any]:
    """Кол-во labeled feedback (по tenant'у или глобально)."""
    try:
        from src.backend.services.ai.feedback.feedback_service import AIFeedbackService

        service = AIFeedbackService()
        items = await service.list_labeled(tenant_id=tenant_id, limit=10_000)
        return {"tenant_id": tenant_id, "count": len(items)}
    except Exception as _:
        return {"tenant_id": tenant_id, "count": 0}
