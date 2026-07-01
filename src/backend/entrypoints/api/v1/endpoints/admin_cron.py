"""Admin cron endpoints — Sprint 12 K3 W2 + K5 W3.

Endpoints (mount /api/v1/admin/cron):

* ``GET /list`` — все scheduled jobs;
* ``POST /schedule`` — зарегистрировать новый cron-job;
* ``DELETE /{id}`` — снять с расписания;
* ``POST /{id}/pause`` / ``POST /{id}/resume`` — пауза/возобновление;
* ``POST /{id}/run-now`` — немедленный запуск (K5 W3);
* ``POST /validate`` — preview Next N executions (без регистрации);
* ``GET /dashboard`` — сводка для page 14 (K5 W3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

__all__ = ("router",)

router = APIRouter(prefix="/admin/cron", tags=["admin", "scheduler"])


class CronJobSummary(BaseModel):
    """Краткое описание scheduled job."""

    id: str
    name: str
    next_run_time: str | None = None
    trigger: str
    paused: bool = False


class CronScheduleRequest(BaseModel):
    """Запрос на создание cron-job."""

    name: str = Field(min_length=1, max_length=120)
    cron_expr: str = Field(min_length=1, max_length=255)
    callable_ref: str = Field(
        description="Module-path ``module.path:function`` для задачи.",
        pattern=r"^[\w.]+:[\w]+$",
    )
    timezone: str = Field(default="Europe/Moscow", max_length=64)


class CronValidationRequest(BaseModel):
    """Запрос на dry-run preview cron-expression."""

    expression: str = Field(min_length=1, max_length=255)
    timezone: str = Field(default="Europe/Moscow", max_length=64)
    preview_count: int = Field(default=5, ge=1, le=50)


class CronValidationResponse(BaseModel):
    """Ответ на validate — preview executions без регистрации job."""

    expression: str
    timezone: str
    is_valid: bool
    next_executions: list[datetime] = Field(default_factory=list)
    error: str | None = None


class CronDashboardSummary(BaseModel):
    """Сводка для page 14 Cron Dashboard."""

    total_jobs: int
    paused_jobs: int
    jobs: list[CronJobSummary] = Field(default_factory=list)


def _resolve_callable(ref: str) -> Any:
    """Резолвит ``module.path:function`` в callable."""
    import importlib

    module_path, _, attr = ref.partition(":")
    if not attr:
        raise ValueError(f"Невалидный callable_ref={ref!r} (нет ':function').")
    module = importlib.import_module(module_path)
    return getattr(module, attr)


@router.get("/list", response_model=list[CronJobSummary])
async def list_cron_jobs() -> list[CronJobSummary]:
    """Возвращает все зарегистрированные cron-jobs."""
    from src.backend.core.scheduler import get_scheduler_manager

    manager = get_scheduler_manager()
    return [CronJobSummary(**j) for j in manager.list_jobs()]


@router.post(
    "/schedule", response_model=CronJobSummary, status_code=status.HTTP_201_CREATED
)
async def schedule_cron_job(request: CronScheduleRequest) -> CronJobSummary:
    """Регистрирует новый cron-job. ``callable_ref`` резолвится importlib."""
    from src.backend.core.scheduler import get_scheduler_manager

    try:
        callable_ref = _resolve_callable(request.callable_ref)
    except (ImportError, AttributeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Невозможно разрешить callable: {exc}",
        ) from exc

    manager = get_scheduler_manager()
    try:
        job_id = manager.schedule_cron(
            name=request.name,
            cron_expr=request.cron_expr,
            callable_ref=callable_ref,
            timezone=request.timezone,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Ошибка регистрации: {exc}"
        ) from exc

    jobs = manager.list_jobs()
    for j in jobs:
        if j["id"] == job_id:
            return CronJobSummary(**j)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Job зарегистрирован, но не найден в list_jobs().",
    )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cron_job(job_id: str) -> None:
    """Удаляет cron-job по id."""
    from src.backend.core.scheduler import get_scheduler_manager

    manager = get_scheduler_manager()
    try:
        manager.scheduler.remove_job(job_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id!r} not found: {exc}",
        ) from exc


@router.post("/{job_id}/pause", status_code=status.HTTP_200_OK)
async def pause_cron_job(job_id: str) -> dict[str, Any]:
    """Приостанавливает scheduled job."""
    from src.backend.core.scheduler import get_scheduler_manager

    ok = get_scheduler_manager().pause_job(job_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id!r} not found"
        )
    return {"id": job_id, "paused": True}


@router.post("/{job_id}/resume", status_code=status.HTTP_200_OK)
async def resume_cron_job(job_id: str) -> dict[str, Any]:
    """Возобновляет paused job."""
    from src.backend.core.scheduler import get_scheduler_manager

    ok = get_scheduler_manager().resume_job(job_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id!r} not found"
        )
    return {"id": job_id, "paused": False}


@router.post("/{job_id}/run-now", status_code=status.HTTP_200_OK)
async def run_cron_job_now(job_id: str) -> dict[str, Any]:
    """Sprint 12 K5 W3 — немедленный запуск job (modify next_run_time)."""
    from src.backend.core.scheduler import get_scheduler_manager

    ok = get_scheduler_manager().run_job_now(job_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id!r} not found"
        )
    return {"id": job_id, "scheduled": "now"}


@router.post("/validate", response_model=CronValidationResponse)
async def validate_cron(request: CronValidationRequest) -> CronValidationResponse:
    """Dry-run preview — валидация выражения + Next N executions."""
    from src.backend.core.scheduler import validate_cron_expression

    result = validate_cron_expression(
        request.expression,
        timezone=request.timezone,
        preview_count=request.preview_count,
    )
    return CronValidationResponse(
        expression=result.expression,
        timezone=result.timezone,
        is_valid=result.is_valid,
        next_executions=list(result.next_executions),
        error=result.error,
    )


@router.get("/dashboard", response_model=CronDashboardSummary)
async def cron_dashboard() -> CronDashboardSummary:
    """Sprint 12 K5 W3 — сводка для page 14."""
    from src.backend.core.scheduler import get_scheduler_manager

    jobs_raw = get_scheduler_manager().list_jobs()
    jobs = [CronJobSummary(**j) for j in jobs_raw]
    paused = sum(1 for j in jobs if j.paused)
    return CronDashboardSummary(total_jobs=len(jobs), paused_jobs=paused, jobs=jobs)
