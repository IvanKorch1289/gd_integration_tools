"""S56 W4 — input_schema.py part of admin_workflows decomp.

Classes: .
Funcs: input_schema_json.
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

def input_schema_json(schema: Any) -> dict[str, Any] | None:
    """Возвращает JSON-Schema Pydantic-модели или ``None``.

    Используется в MCP auto-export (``workflow_tools.py``) для
    формирования ``inputSchema`` MCP tool'а.
    """
    if schema is None:
        return None
    try:
        return TypeAdapter(schema).json_schema()
    except Exception as _:
        return None

