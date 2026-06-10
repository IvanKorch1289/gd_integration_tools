"""S56 W4 — schemas.py part of admin_workflows decomp.

Classes: WorkflowInstanceIdPath, WorkflowNamePath, ListWorkflowsQuery, EventsQuery, TriggerQuery, TriggerBody.
Funcs: .
"""
from __future__ import annotations

"""Admin REST API для durable workflows (IL-WF1.5).

W26.5: маршруты регистрируются декларативно через ActionSpec; per-endpoint
бизнес-логика вынесена в локальный ``_AdminWorkflowsFacade``.

Endpoints (под /api/v1/admin):

    * GET    /workflows                          — list + фильтрация.
    * GET    /workflows/{instance_id}            — header + event log.
    * GET    /workflows/{instance_id}/events     — paginated events.
    * POST   /workflows/{instance_id}/retry      — force retry.
    * POST   /workflows/{instance_id}/cancel     — graceful cancel.
    * POST   /workflows/{instance_id}/resume     — resume paused.
    * POST   /workflows/trigger/{workflow_name}  — universal trigger.

Авторизация: эндпоинты монтируются под ``/admin`` — защищены
глобальным :class:`APIKeyMiddleware`.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, TypeAdapter

from src.backend.core.logging import get_logger
from src.backend.entrypoints.api.generator.actions import (
    ActionRouterBuilder,
    ActionSpec,
)
from src.backend.entrypoints.base import dispatch_action

# Wave 6.5a: типы для type-hints импортируются через TYPE_CHECKING, чтобы
# не нарушать layer policy (entrypoints → infrastructure запрещено).
# Runtime-доступ к классам — через core.di.providers (lazy importlib).
from src.backend.schemas.workflow import (
    WorkflowCancelRequest,
    WorkflowEventSchemaOut,
    WorkflowInstanceDetailSchemaOut,
    WorkflowInstanceRef,
    WorkflowInstanceSchemaOut,
)
from src.backend.workflows.registry import workflow_registry

# Wave 6.5a: ``WorkflowStatus`` нужен Pydantic'у на этапе построения
# схемы ``ListWorkflowsQuery`` (форвард-референс резолвится через
# модульный namespace), поэтому единожды резолвится через DI provider
# при импорте этого модуля. Это сохраняет статический check_layers.py
# чистым (нет AST-импорта infrastructure), но на runtime даёт
# конкретный enum.

class WorkflowInstanceIdPath(BaseModel):
    """Path-параметр UUID workflow-инстанса."""

    instance_id: UUID = Field(..., description="UUID workflow-инстанса.")

class WorkflowNamePath(BaseModel):
    """Path-параметр логического имени workflow."""

    workflow_name: str = Field(..., description="Логическое имя workflow.")

class ListWorkflowsQuery(BaseModel):
    """Query-параметры для /workflows list."""

    status_filter: WorkflowStatus | None = Field(
        default=None, alias="status", description="Фильтр по статусу инстанса."
    )
    workflow_name: str | None = Field(
        default=None, description="Фильтр по логическому имени workflow."
    )
    tenant_id: str | None = Field(default=None, description="Фильтр по tenant scope.")
    limit: int = Field(default=50, ge=1, le=500, description="Максимум записей.")

class EventsQuery(BaseModel):
    """Query-параметры paginated event log."""

    after_seq: int = Field(default=0, ge=0, description="Cursor — нижняя граница seq.")
    limit: int = Field(default=100, ge=1, le=1000, description="Максимум событий.")

class TriggerQuery(BaseModel):
    """Query-параметры trigger-эндпоинта."""

    wait: bool = Field(
        default=False, description="Ждать завершения (polling до terminal или timeout)."
    )
    timeout_s: int = Field(
        default=30, ge=1, le=600, description="Timeout ожидания (только при wait=True)."
    )

class TriggerBody(BaseModel):
    """Тело trigger-эндпоинта (произвольный payload)."""

    model_config = {"extra": "allow"}

