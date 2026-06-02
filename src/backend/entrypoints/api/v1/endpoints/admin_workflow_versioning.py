"""Admin workflow versioning endpoints — Sprint 12 K3 W8.

Endpoints (mount /api/v1/admin/workflow-versioning):

* ``GET /{workflow_id}/history`` — все версии workflow;
* ``POST /{workflow_id}/pin?semver=X.Y.Z`` — pin указанную как default;
* ``POST /{workflow_id}/rollback`` — откат на предыдущую default-версию;
* ``GET /{workflow_id}/running-count`` — счётчик running executions по
  версии (через Temporal Client).
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

__all__ = ("router",)

router = APIRouter(
    prefix="/admin/workflow-versioning", tags=["admin", "workflow", "versioning"]
)


_SEMVER_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")


class WorkflowVersionResponse(BaseModel):
    """Версия workflow."""

    workflow_id: str
    semver: str
    major: int
    minor: int
    patch: int
    default_version: bool


class RollbackResponse(BaseModel):
    """Ответ POST /rollback."""

    rolled_back: bool
    new_default: WorkflowVersionResponse | None = None


class RunningCountResponse(BaseModel):
    """Ответ GET /running-count."""

    workflow_id: str
    counts: dict[str, int]


def _to_response(v: Any) -> WorkflowVersionResponse:
    return WorkflowVersionResponse(
        workflow_id=v.workflow_id,
        semver=v.semver,
        major=v.major,
        minor=v.minor,
        patch=v.patch,
        default_version=v.default_version,
    )


@router.get("/{workflow_id}/history", response_model=list[WorkflowVersionResponse])
async def get_workflow_history(workflow_id: str) -> list[WorkflowVersionResponse]:
    """Возвращает все зарегистрированные версии workflow."""
    from src.backend.dsl.workflow.versioning import get_global_registry

    history = get_global_registry().history(workflow_id)
    return [_to_response(v) for v in history]


@router.post("/{workflow_id}/pin", response_model=WorkflowVersionResponse)
async def pin_workflow_version(
    workflow_id: str, semver: str = Query(..., min_length=3, max_length=20)
) -> WorkflowVersionResponse:
    """Pin указанную версию как default для workflow."""
    if not _SEMVER_RE.match(semver):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Невалидный semver {semver!r}. Допустимо X.Y или X.Y.Z.",
        )

    from src.backend.dsl.workflow.versioning import get_global_registry

    try:
        updated = get_global_registry().pin_default(workflow_id, semver=semver)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _to_response(updated)


@router.post("/{workflow_id}/rollback", response_model=RollbackResponse)
async def rollback_workflow_version(workflow_id: str) -> RollbackResponse:
    """Откатить default на предыдущую версию."""
    from src.backend.dsl.workflow.versioning import get_global_registry

    new_default = get_global_registry().rollback(workflow_id)
    if new_default is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Невозможно откатиться: нет предыдущей default-версии "
                f"для {workflow_id!r}."
            ),
        )
    return RollbackResponse(rolled_back=True, new_default=_to_response(new_default))


@router.get("/{workflow_id}/running-count", response_model=RunningCountResponse)
async def get_running_count(workflow_id: str) -> RunningCountResponse:
    """Sprint 12 K3 W8 — count running executions per version.

    Под капотом обращается к Temporal Client (lazy import; при отсутствии
    SDK или connection возвращает пустой dict).
    """
    counts: dict[str, int] = {}
    try:
        from src.backend.infrastructure.workflow.factory import create_workflow_backend

        backend = await create_workflow_backend(kind="auto")
        if hasattr(backend, "count_running_per_version"):
            counts = await backend.count_running_per_version(  
                workflow_id=workflow_id
            )
    except Exception as _:  # noqa: BLE001
        counts = {}
    return RunningCountResponse(workflow_id=workflow_id, counts=counts)
