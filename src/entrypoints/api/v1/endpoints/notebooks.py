"""REST API для notebooks (Wave 9.1, мигрировано на ActionRouterBuilder в W26.5).

Эндпоинты ``/api/v1/notebooks/*`` — CRUD + история версий + restore.
Backend — ``NotebookService`` (Mongo с fallback на in-memory).

После W26.5: маршруты регистрируются декларативно через ActionSpec;
прямых ``@router.get/.post`` нет — каждый action идёт через
``ActionRouterBuilder`` и доступен по единому контракту action-bus.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.entrypoints.api.generator.actions import ActionRouterBuilder, ActionSpec
from src.services.notebooks import get_notebook_service
from src.services.notebooks.models import Notebook, NotebookVersion

__all__ = ("router",)


# --- Path / Query schemas --------------------------------------------------


class NotebookIdPath(BaseModel):
    """Path-параметр идентификатора notebook'а."""

    notebook_id: str = Field(..., description="ID notebook'а.")


class NotebookIdVersionPath(BaseModel):
    """Path-параметры notebook + version."""

    notebook_id: str = Field(..., description="ID notebook'а.")
    version: int = Field(..., description="Номер версии notebook'а.")


class NotebookListQuery(BaseModel):
    """Query-параметры списочного эндпоинта."""

    tag: str | None = Field(default=None, description="Фильтр по тегу.")
    include_deleted: bool = Field(
        default=False, description="Включить soft-deleted notebooks."
    )
    limit: int = Field(default=50, ge=1, le=500, description="Размер страницы.")
    offset: int = Field(default=0, ge=0, description="Смещение для пагинации.")


class RestoreUserQuery(BaseModel):
    """Query-параметр пользователя для restore."""

    user: str = Field(..., description="Пользователь, инициирующий restore.")


# --- Body schemas ----------------------------------------------------------


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


# --- Response schemas ------------------------------------------------------


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


class NotebookDeleteOut(BaseModel):
    """Ответ delete-эндпоинта."""

    deleted: bool


# --- Response handlers (404 / преобразования) ------------------------------


def _to_out(notebook: Notebook) -> NotebookOut:
    """Notebook → NotebookOut (облегчённое представление)."""
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


def _list_handler(result: list[Notebook], _: dict[str, Any]) -> list[NotebookOut]:
    return [_to_out(n) for n in result]


def _require_notebook(result: Notebook | None, _: dict[str, Any]) -> Notebook:
    if result is None:
        raise HTTPException(status_code=404, detail="Notebook не найден")
    return result


def _require_version(
    result: NotebookVersion | None, kwargs: dict[str, Any]
) -> NotebookVersion:
    if result is None:
        version = kwargs.get("version")
        raise HTTPException(
            status_code=404, detail=f"Notebook или версия {version} не найдены"
        )
    return result


async def _list_versions_handler(
    result: list[NotebookVersion], kwargs: dict[str, Any]
) -> list[NotebookVersion]:
    """Если версий нет — проверяем существование самого notebook'а.

    Сохраняет legacy-поведение: пустой список для существующего notebook'а
    допустим, но 404 — если notebook отсутствует.
    """
    if result:
        return result
    notebook_id = kwargs.get("notebook_id")
    if notebook_id is None:
        return result
    notebook = await get_notebook_service().get(notebook_id)
    if notebook is None:
        raise HTTPException(status_code=404, detail="Notebook не найден")
    return result


def _delete_handler(result: bool, _: dict[str, Any]) -> NotebookDeleteOut:
    if not result:
        raise HTTPException(status_code=404, detail="Notebook не найден")
    return NotebookDeleteOut(deleted=True)


def _restore_handler(result: Notebook | None, kwargs: dict[str, Any]) -> Notebook:
    if result is None:
        version = kwargs.get("version")
        raise HTTPException(
            status_code=404, detail=f"Notebook или версия {version} не найдены"
        )
    return result


# --- Router ----------------------------------------------------------------


router = APIRouter()
builder = ActionRouterBuilder(router)

common_tags = ("Notebooks",)


builder.add_actions(
    [
        ActionSpec(
            name="create_notebook",
            method="POST",
            path="",
            summary="Создать новый notebook",
            description="Создаёт новый notebook (с опциональной первой версией контента).",
            service_getter=get_notebook_service,
            service_method="create",
            body_model=NotebookCreateIn,
            response_model=Notebook,
            status_code=status.HTTP_201_CREATED,
            tags=common_tags,
        ),
        ActionSpec(
            name="list_notebooks",
            method="GET",
            path="",
            summary="Список notebooks",
            description="Список notebooks с фильтром по тегу и пагинацией.",
            service_getter=get_notebook_service,
            service_method="list_all",
            query_model=NotebookListQuery,
            response_model=list[NotebookOut],
            response_handler=_list_handler,
            tags=common_tags,
        ),
        ActionSpec(
            name="get_notebook",
            method="GET",
            path="/{notebook_id}",
            summary="Получить notebook со всеми версиями",
            service_getter=get_notebook_service,
            service_method="get",
            path_model=NotebookIdPath,
            response_model=Notebook,
            response_handler=_require_notebook,
            tags=common_tags,
        ),
        ActionSpec(
            name="list_notebook_versions",
            method="GET",
            path="/{notebook_id}/versions",
            summary="История версий notebook'а",
            service_getter=get_notebook_service,
            service_method="list_versions",
            path_model=NotebookIdPath,
            response_model=list[NotebookVersion],
            response_handler=_list_versions_handler,
            tags=common_tags,
        ),
        ActionSpec(
            name="get_notebook_version",
            method="GET",
            path="/{notebook_id}/versions/{version}",
            summary="Получить конкретную версию notebook'а",
            service_getter=get_notebook_service,
            service_method="get_version",
            path_model=NotebookIdVersionPath,
            response_model=NotebookVersion,
            response_handler=_require_version,
            tags=common_tags,
        ),
        ActionSpec(
            name="append_notebook_version",
            method="POST",
            path="/{notebook_id}/versions",
            summary="Добавить новую версию контента",
            description="Append-only обновление контента notebook'а.",
            service_getter=get_notebook_service,
            service_method="update_content",
            path_model=NotebookIdPath,
            body_model=NotebookUpdateIn,
            response_model=Notebook,
            response_handler=_require_notebook,
            tags=common_tags,
        ),
        ActionSpec(
            name="restore_notebook_version",
            method="POST",
            path="/{notebook_id}/restore/{version}",
            summary="Восстановить версию notebook'а",
            description="Создаёт новую версию notebook'а с контентом указанной старой версии.",
            service_getter=get_notebook_service,
            service_method="restore_version",
            path_model=NotebookIdVersionPath,
            query_model=RestoreUserQuery,
            response_model=Notebook,
            response_handler=_restore_handler,
            tags=common_tags,
        ),
        ActionSpec(
            name="delete_notebook",
            method="DELETE",
            path="/{notebook_id}",
            summary="Soft-delete notebook'а",
            service_getter=get_notebook_service,
            service_method="delete",
            path_model=NotebookIdPath,
            response_model=NotebookDeleteOut,
            response_handler=_delete_handler,
            tags=common_tags,
        ),
    ]
)
