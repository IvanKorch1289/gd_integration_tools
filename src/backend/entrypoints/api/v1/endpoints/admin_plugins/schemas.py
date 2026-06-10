from __future__ import annotations
"""S62 W1 — schemas.py part of admin_plugins decomp.

11 Pydantic schemas for plugin admin API.
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.backend.core.logging import get_logger

router = APIRouter(prefix="/admin/plugins", tags=["admin"])

# ─── Pydantic-схемы запроса/ответа ────────────────────────────────────────────

class PluginSummary(BaseModel):
    """Краткое описание плагина из реестра."""

    name: str
    version: str
    status: str  # "active" | "inactive" | "error"
    capabilities: list[str] = Field(default_factory=list)
    routes_count: int = 0
    actions_count: int = 0

class PluginManifest(BaseModel):
    """Содержимое plugin.toml в структурированном виде."""

    name: str
    version: str
    requires_core: str
    capabilities: list[str] = Field(default_factory=list)
    tenant_aware: bool = False
    provides: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(
        default_factory=dict, description="Сырое содержимое TOML"
    )

class PluginToggleRequest(BaseModel):
    """Тело запроса POST /{name}/toggle."""

    active: bool = Field(..., description="True — активировать, False — деактивировать")

class PluginToggleResponse(BaseModel):
    """Результат операции toggle."""

    name: str
    active: bool
    previous_status: str
    current_status: str

class PluginVersionsResponse(BaseModel):
    """Список локально установленных версий плагина."""

    plugin: str
    versions: list[dict[str, Any]]

class PluginDiffResponse(BaseModel):
    """Diff двух версий плагина (см. MigrationDiffer)."""

    plugin: str
    from_version: str
    to_version: str
    payload: dict[str, Any]

class PluginRollbackRequest(BaseModel):
    """Тело запроса POST /{name}/rollback."""

    to_version: str = Field(..., description="Целевая версия (SemVer).")

class PluginRollbackResponse(BaseModel):
    """Результат rollback-операции."""

    plugin: str
    from_version: str
    to_version: str
    status: str
    reason: str | None = None

class PluginDependencyGraph(BaseModel):
    """Граф зависимостей плагинов (для Streamlit Mermaid визуализации)."""

    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, str]] = Field(default_factory=list)

class PluginScaffoldRequest(BaseModel):
    """Тело POST /plugins/scaffold."""

    name: str = Field(..., description="snake_case имя плагина", min_length=1)
    description: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    dry_run: bool = False

class PluginScaffoldResponse(BaseModel):
    """Результат scaffold-операции."""

    name: str
    created: bool
    path: str | None = None
    dry_run: bool = False
    actions: list[str] = Field(default_factory=list)

