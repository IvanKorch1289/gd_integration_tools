"""Admin REST для Scheduler DLQ (Sprint 21 W4, G-09 closure).

Endpoints:

* ``GET /admin/scheduler/dlq`` — список failed jobs (новейшие сверху).
* ``GET /admin/scheduler/dlq/{entry_id}`` — детали одной записи.
* ``POST /admin/scheduler/dlq/{entry_id}/retry`` — увеличить retry_count
  и попытаться перезапустить job через :class:`AsyncIOScheduler`. Если
  scheduler не доступен — только инкрементирует счётчик.
* ``DELETE /admin/scheduler/dlq/{entry_id}`` — удалить запись из store.

Защищён ``require_admin((AdminRole.OPERATOR, AdminRole.SUPER_ADMIN))``.

Feature-flag:
    ``scheduler_dlq_enabled`` (W0). При False endpoints возвращают пустой
    список / 404 (store отсутствует).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.backend.core.auth.admin_roles import AdminRole, require_admin
from src.backend.infrastructure.scheduler.dlq import (
    SchedulerDLQStore,
    get_scheduler_dlq_store,
)

__all__ = ("router",)

router = APIRouter(prefix="/admin/scheduler/dlq", tags=["Admin / Scheduler"])


def _require_store() -> SchedulerDLQStore:
    store = get_scheduler_dlq_store()
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Scheduler DLQ store не инициализирован; "
                "проверьте feature_flags.scheduler_dlq_enabled и lifespan."
            ),
        )
    return store


@router.get(
    "",
    response_model=list[dict[str, Any]],
    dependencies=[Depends(require_admin((AdminRole.OPERATOR, AdminRole.SUPER_ADMIN)))],
)
async def list_failed_jobs(
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Возвращает failed scheduler jobs (новейшие сверху)."""
    store = _require_store()
    return [entry.to_dict() for entry in store.list(limit=limit)]


@router.get(
    "/{entry_id}",
    response_model=dict[str, Any],
    dependencies=[
        Depends(
            require_admin(
                (AdminRole.OPERATOR, AdminRole.SUPER_ADMIN, AdminRole.READ_ONLY)
            )
        )
    ],
)
async def get_failed_job(entry_id: str) -> dict[str, Any]:
    """Возвращает одну DLQ-запись по id."""
    store = _require_store()
    entry = store.get(entry_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="DLQ entry not found"
        )
    return entry.to_dict()


@router.post(
    "/{entry_id}/retry",
    response_model=dict[str, Any],
    dependencies=[Depends(require_admin((AdminRole.OPERATOR, AdminRole.SUPER_ADMIN)))],
)
async def retry_failed_job(entry_id: str) -> dict[str, Any]:
    """Помечает retry_count++ и (если scheduler доступен) пытается перезапустить job.

    Возвращает обновлённую запись + ``reschedule_attempted`` boolean.
    """
    store = _require_store()
    entry = store.get(entry_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="DLQ entry not found"
        )
    entry.mark_retried()

    reschedule_attempted = False
    try:
        from src.backend.infrastructure.scheduler.scheduler_manager import (
            get_scheduler_manager,
        )

        manager = get_scheduler_manager()
        scheduler = getattr(manager, "scheduler", None)
        if scheduler is not None and scheduler.get_job(entry.job_id) is not None:
            scheduler.reschedule_job(entry.job_id)
            reschedule_attempted = True
    except Exception as _:  # noqa: BLE001
        reschedule_attempted = False

    return {**entry.to_dict(), "reschedule_attempted": reschedule_attempted}


@router.delete(
    "/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin((AdminRole.OPERATOR, AdminRole.SUPER_ADMIN)))],
)
async def delete_failed_job(entry_id: str) -> None:
    """Удаляет DLQ-запись из in-memory store."""
    store = _require_store()
    if not store.delete(entry_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="DLQ entry not found"
        )
