"""REST API для notebooks (Wave 9.1).

Эндпоинты ``/api/v1/notebooks/*`` — CRUD + история версий + restore.
Backend — ``NotebookService`` (Mongo с fallback на in-memory).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.services.notebooks import get_notebook_service
from src.services.notebooks.models import Notebook, NotebookVersion

__all__ = ("router",)

router = APIRouter()


class NotebookCreateIn(BaseModel):
    """Запрос на создание notebook'а."""

    title: str
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    created_by: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class NotebookUpdateIn(BaseModel):
    """Запрос на новую версию контента."""

    content: str
    user: str
    summary: str | None = None


class NotebookOut(BaseModel):
    """Облегчённое представление notebook'а для list-эндпоинта."""

    id: str
    title: str
    tags: list[str]
    latest_version: int
    created_by: str
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


def _to_out(notebook: Notebook) -> NotebookOut:
    return NotebookOut(
        id=notebook.id,
        title=notebook.title,
        tags=notebook.tags,
        latest_version=notebook.latest_version,
        created_by=notebook.created_by,
        created_at=notebook.created_at,
        updated_at=notebook.updated_at,
        is_deleted=notebook.is_deleted,
    )


@router.post("", response_model=Notebook, status_code=status.HTTP_201_CREATED)
async def create_notebook(payload: NotebookCreateIn) -> Notebook:
    """Создаёт новый notebook (с опциональной первой версией контента)."""
    service = get_notebook_service()
    return await service.create(
        title=payload.title,
        content=payload.content,
        created_by=payload.created_by,
        tags=payload.tags,
        metadata=payload.metadata,
    )


@router.get("", response_model=list[NotebookOut])
async def list_notebooks(
    tag: str | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[NotebookOut]:
    """Список notebooks с фильтром по тегу и пагинацией."""
    service = get_notebook_service()
    docs = await service.list_all(
        tag=tag, include_deleted=include_deleted, limit=limit, offset=offset
    )
    return [_to_out(d) for d in docs]


@router.get("/{notebook_id}", response_model=Notebook)
async def get_notebook(notebook_id: str) -> Notebook:
    """Возвращает notebook со всеми версиями."""
    service = get_notebook_service()
    notebook = await service.get(notebook_id)
    if notebook is None:
        raise HTTPException(status_code=404, detail="Notebook не найден")
    return notebook


@router.get("/{notebook_id}/versions", response_model=list[NotebookVersion])
async def list_versions(notebook_id: str) -> list[NotebookVersion]:
    """История версий notebook'а."""
    service = get_notebook_service()
    versions = await service.list_versions(notebook_id)
    if not versions:
        notebook = await service.get(notebook_id)
        if notebook is None:
            raise HTTPException(status_code=404, detail="Notebook не найден")
    return versions


@router.get("/{notebook_id}/versions/{version}", response_model=NotebookVersion)
async def get_version(notebook_id: str, version: int) -> NotebookVersion:
    """Возвращает конкретную версию по номеру."""
    service = get_notebook_service()
    result = await service.get_version(notebook_id, version)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"Notebook или версия {version} не найдены"
        )
    return result


@router.post("/{notebook_id}/versions", response_model=Notebook)
async def append_version(notebook_id: str, payload: NotebookUpdateIn) -> Notebook:
    """Добавляет новую версию контента (append-only)."""
    service = get_notebook_service()
    notebook = await service.update_content(
        notebook_id=notebook_id,
        content=payload.content,
        user=payload.user,
        summary=payload.summary,
    )
    if notebook is None:
        raise HTTPException(status_code=404, detail="Notebook не найден")
    return notebook


@router.post("/{notebook_id}/restore/{version}", response_model=Notebook)
async def restore_version(notebook_id: str, version: int, user: str) -> Notebook:
    """Восстанавливает указанную версию как новую (append-only)."""
    service = get_notebook_service()
    notebook = await service.restore_version(
        notebook_id=notebook_id, version=version, user=user
    )
    if notebook is None:
        raise HTTPException(
            status_code=404, detail=f"Notebook или версия {version} не найдены"
        )
    return notebook


@router.delete("/{notebook_id}")
async def delete_notebook(notebook_id: str) -> dict[str, bool]:
    """Soft delete notebook'а (флаг ``is_deleted=True``)."""
    service = get_notebook_service()
    deleted = await service.delete(notebook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Notebook не найден")
    return {"deleted": True}
