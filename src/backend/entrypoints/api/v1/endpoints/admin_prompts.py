"""Admin REST API для версий промптов (ADR-0437).

Endpoints (под ``/api/v1/admin``):

* ``GET /prompt-versions`` — список промптов и их версий;
* ``GET /prompt-versions/{name}`` — версии конкретного промпта;
* ``POST /prompt-versions`` — регистрация новой версии;
* ``POST /prompt-versions/{name}/activate`` — активация версии (production);
* ``GET /prompt-versions/{name}/compare`` — A/B-сравнение двух версий.

Авторизация: admin-роль (``OPERATOR`` / ``SUPER_ADMIN``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.backend.core.auth.admin_roles import AdminRole, require_admin
from src.backend.core.logging import get_logger

__all__ = ("router",)

logger = get_logger("entrypoints.admin_prompts")

_ADMIN_GUARD = Depends(require_admin((AdminRole.OPERATOR, AdminRole.SUPER_ADMIN)))

router = APIRouter(dependencies=[_ADMIN_GUARD])


class PromptVersionCreate(BaseModel):
    """Запрос на регистрацию версии промпта."""

    name: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, description="Шаблон промпта.")
    version: int | None = Field(
        default=None, ge=1, description="Номер версии (по умолчанию — следующий)."
    )
    model: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None


def _registry() -> Any:
    """Реестр промптов из DI."""
    from src.backend.core.di.providers.prompts import get_prompt_registry_provider

    return get_prompt_registry_provider()


class PromptActivate(BaseModel):
    """Запрос на активацию версии промпта."""

    version: int = Field(ge=1)


@router.get(
    "/prompt-versions",
    summary="Промпты и их версии",
    description="Список зарегистрированных промптов с версиями и активной версией.",
    tags=["Admin · Prompts"],
    responses={200: {"description": "Список промптов."}},
)
async def list_prompt_versions() -> list[dict[str, Any]]:
    """Все промпты с их версиями."""
    registry = _registry()
    return [
        {
            "name": name,
            "active_version": registry.active_version(name),
            "versions": registry.list_versions(name),
        }
        for name in registry.list_prompts()
    ]


@router.get(
    "/prompt-versions/{name}",
    summary="Версии промпта",
    description="Версии конкретного промпта (template + активная версия).",
    tags=["Admin · Prompts"],
    responses={
        200: {"description": "Версии промпта."},
        404: {"description": "Промпт не найден."},
    },
)
async def list_prompt_name_versions(name: str) -> dict[str, Any]:
    """Версии одного промпта."""
    registry = _registry()
    versions = registry.list_versions(name)
    if not versions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Промпт {name!r} не найден"
        )
    return {
        "name": name,
        "active_version": registry.active_version(name),
        "versions": versions,
    }


@router.post(
    "/prompt-versions",
    summary="Зарегистрировать версию промпта",
    description="Регистрирует новую версию шаблона промпта (fallback-режим).",
    tags=["Admin · Prompts"],
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Версия зарегистрирована."},
        409: {"description": "Такая версия уже зарегистрирована."},
    },
)
async def create_prompt_version(request: PromptVersionCreate) -> dict[str, Any]:
    """Зарегистрировать новую версию промпта."""
    registry = _registry()
    existing = {item["version"] for item in registry.list_versions(request.name)}
    version = request.version
    if version is None:
        version = (max(existing) + 1) if existing else 1
    if version in existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Версия {version} промпта {request.name!r} уже существует",
        )
    labels = {"source": "fallback"}
    if request.created_by:
        labels["created_by"] = request.created_by
    registry.register(
        request.name, template=request.body, version=version, labels=labels
    )
    return {"name": request.name, "version": version, "created": True}


@router.post(
    "/prompt-versions/{name}/activate",
    summary="Активировать версию промпта",
    description="Переводит версию в label production (активную).",
    tags=["Admin · Prompts"],
    responses={
        200: {"description": "Версия активирована."},
        404: {"description": "Промпт или версия не найдены."},
    },
)
async def activate_prompt_version(name: str, request: PromptActivate) -> dict[str, Any]:
    """Активировать версию промпта."""
    registry = _registry()
    version = request.version
    if not registry.activate(name, version):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Версия {version} промпта {name!r} не найдена",
        )
    return {"name": name, "version": version, "active": True}


@router.get(
    "/prompt-versions/{name}/compare",
    summary="A/B-сравнение версий промпта",
    description=(
        "Сравнение шаблонов двух версий. ``metric_diffs`` заполняется, только "
        "если доступны метрики Langfuse; иначе возвращается diff шаблонов."
    ),
    tags=["Admin · Prompts"],
    responses={
        200: {"description": "Результат сравнения."},
        404: {"description": "Промпт или версия не найдены."},
    },
)
async def compare_prompt_versions(
    name: str, a: int = Query(ge=1), b: int = Query(ge=1)
) -> dict[str, Any]:
    """Сравнить две версии промпта."""
    registry = _registry()
    try:
        return registry.compare(name, a, b)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
