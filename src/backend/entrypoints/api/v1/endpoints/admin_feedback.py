"""Admin REST для AI Feedback dashboard (Sprint 11 K5 W2).

* ``GET /admin/feedback/training-runs`` — список последних training runs
  DSPy с метаданными.
* ``GET /admin/feedback/labeled-count`` — кол-во labeled feedback per
  tenant (для UI).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from src.backend.core.auth.admin_roles import AdminRole, require_admin

logger = logging.getLogger(__name__)

# S202 audit fix: require admin role
_ADMIN_GUARD_READ = Depends(
    require_admin((AdminRole.OPERATOR, AdminRole.READ_ONLY, AdminRole.SUPER_ADMIN))
)

router = APIRouter(
    dependencies=[_ADMIN_GUARD_READ],
    prefix="/admin/feedback",
    tags=["admin", "feedback"],
)


@router.get(
    "/training-runs",
    summary="Последние DSPy training runs",
    description=(
        "Возвращает список завершённых DSPy training runs с метаданными "
        "(id, dataset, model, accuracy, started_at, finished_at). "
        "В production runs хранятся в LangfusePromptStorage; пока возвращается "
        "пустой список — отображается заголовок «Нет завершённых runs». "
        "Используется в Admin UI /admin/feedback dashboard."
    ),
    tags=["admin", "feedback"],
    responses={
        200: {"description": "Список training runs (может быть пустой)."},
        500: {"description": "Ошибка чтения из storage backend."},
    },
)
async def list_training_runs(limit: int = 10) -> dict[str, Any]:
    """Последние DSPy training runs (in-memory stub; storage TBD).

    В production runs хранятся в LangfusePromptStorage; пока возвращается
    пустой список — отображается заголовок «Нет завершённых runs».

    D-AUDIT-10901 fix (cycle 109, API-P1-009): добавлен explicit
    stub=True + NOTE в payload. Раньше: 'runs: []' silent → admin UI
    не отличал 'реально пусто' от 'storage не подключён'. Теперь
    stub=True + warn-лог при каждом вызове — UI может показать
    warning banner ("Storage not configured"), ops увидит signal.
    """
    logger.warning(
        "list_training_runs: LangfusePromptStorage не подключён "
        "(in-memory stub) — returning empty list. limit=%d",
        limit,
    )
    return {
        "runs": [],
        "count": 0,
        "limit": limit,
        "stub": True,
        "note": "LangfusePromptStorage не подключён (in-memory stub). "
        "Training runs history unavailable until storage integration.",
    }


@router.get(
    "/labeled-count",
    summary="Кол-во labeled feedback per tenant",
    description=(
        "Возвращает количество labeled feedback (использованных для "
        "DSPy fine-tuning) per tenant_id или глобально (если tenant_id=None). "
        "Используется в Admin UI для отображения прогресса разметки."
    ),
    tags=["admin", "feedback"],
    responses={
        200: {"description": "Count of labeled feedback (может быть 0)."},
        500: {"description": "Ошибка чтения из feedback service."},
    },
)
async def labeled_count(tenant_id: str | None = None) -> dict[str, Any]:
    """Кол-во labeled feedback (по tenant'у или глобально).

    D-AUDIT-9901 fix (cycle 99, API-P1-009): bare 'except Exception'
    заменён на narrow + WARNING-лог. Раньше: silent return count=0
    при ЛЮБОМ exception (ImportError AIFeedbackService, AttributeError
    list_labeled mismatch, OSError storage backend) — admin UI
    показывал '0 labeled', хотя реально storage мог быть сломан.
    """
    try:
        from src.backend.services.ai.feedback.feedback_service import AIFeedbackService

        service = AIFeedbackService()
        items = await service.list_labeled(tenant_id=tenant_id, limit=10_000)
        return {"tenant_id": tenant_id, "count": len(items)}
    except (ImportError, AttributeError, OSError) as exc:
        logger.warning(
            "AIFeedbackService.list_labeled failed (tenant_id=%s): "
            "exc_type=%s exc_msg=%s — returning count=0 (possible storage degradation)",
            tenant_id,
            type(exc).__name__,
            exc,
        )
        return {"tenant_id": tenant_id, "count": 0, "stub": True}
