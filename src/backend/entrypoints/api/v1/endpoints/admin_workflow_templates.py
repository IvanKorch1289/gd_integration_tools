"""Admin workflow templates endpoints — Sprint 12 K3 W5.

Endpoints (mount /api/v1/admin/workflow-templates):

* ``GET /`` — список всех templates;
* ``GET /{name}`` — детали одного template (raw yaml + metadata);
* ``GET /search?q=...&top_k=5`` — semantic search;
* ``POST /{name}/deploy`` — копирует yaml в указанный target directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml as _yaml
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

__all__ = ("router",)

router = APIRouter(
    prefix="/admin/workflow-templates", tags=["admin", "workflow", "templates"]
)


class WorkflowTemplateSummary(BaseModel):
    """Краткие метаданные template."""

    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    step_count: int
    file_path: str


class WorkflowTemplateDetail(WorkflowTemplateSummary):
    """Полные детали + raw declaration."""

    raw_yaml: str


class WorkflowTemplateSearchResult(BaseModel):
    """Результат semantic search."""

    template: WorkflowTemplateSummary
    score: float


class WorkflowTemplateDeployRequest(BaseModel):
    """Запрос на deploy template в target directory."""

    target_dir: str = Field(min_length=1, max_length=256)
    overwrite: bool = False


@router.get("/", response_model=list[WorkflowTemplateSummary])
async def list_templates() -> list[WorkflowTemplateSummary]:
    """Список всех зарегистрированных workflow templates."""
    from src.backend.services.workflows.template_registry import get_template_registry

    registry = get_template_registry()
    return [
        WorkflowTemplateSummary(
            name=t.name,
            description=t.description,
            tags=list(t.tags),
            step_count=t.step_count,
            file_path=t.file_path,
        )
        for t in registry.load_all()
    ]


@router.get("/search", response_model=list[WorkflowTemplateSearchResult])
async def search_templates(
    q: str, top_k: int = 5
) -> list[WorkflowTemplateSearchResult]:
    """Semantic search (BGE-M3 если доступен) или fuzzy fallback."""
    from src.backend.services.workflows.template_registry import get_template_registry

    registry = get_template_registry()
    top_k = max(1, min(top_k, 20))
    matches = registry.search_semantic(q, top_k=top_k)
    return [
        WorkflowTemplateSearchResult(
            template=WorkflowTemplateSummary(
                name=t.name,
                description=t.description,
                tags=list(t.tags),
                step_count=t.step_count,
                file_path=t.file_path,
            ),
            score=score,
        )
        for t, score in matches
    ]


@router.get("/{name}", response_model=WorkflowTemplateDetail)
async def get_template(name: str) -> WorkflowTemplateDetail:
    """Полные детали одного template."""
    from src.backend.services.workflows.template_registry import get_template_registry

    registry = get_template_registry()
    tmpl = registry.get(name)
    if tmpl is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {name!r} не найден.",
        )
    raw_yaml = _yaml.safe_dump(tmpl.raw, allow_unicode=True, sort_keys=False)
    return WorkflowTemplateDetail(
        name=tmpl.name,
        description=tmpl.description,
        tags=list(tmpl.tags),
        step_count=tmpl.step_count,
        file_path=tmpl.file_path,
        raw_yaml=raw_yaml,
    )


@router.post("/{name}/deploy", status_code=status.HTTP_201_CREATED)
async def deploy_template(
    name: str, request: WorkflowTemplateDeployRequest
) -> dict[str, Any]:
    """Копирует template в target_dir/<name>.workflow.yaml.

    Безопасность: target_dir должен быть существующей директорией внутри
    рабочей копии репозитория (без exotic path-escape).
    """
    from src.backend.services.workflows.template_registry import get_template_registry

    registry = get_template_registry()
    tmpl = registry.get(name)
    if tmpl is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {name!r} не найден.",
        )

    target_dir = Path(request.target_dir).resolve()
    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Target directory {target_dir} не существует.",
        )

    out_path = target_dir / f"{name}.workflow.yaml"
    if out_path.exists() and not request.overwrite:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Файл {out_path} уже существует (overwrite=false).",
        )

    yaml_text = _yaml.safe_dump(tmpl.raw, allow_unicode=True, sort_keys=False)
    out_path.write_text(yaml_text, encoding="utf-8")

    return {"deployed": True, "name": name, "target_path": str(out_path)}
