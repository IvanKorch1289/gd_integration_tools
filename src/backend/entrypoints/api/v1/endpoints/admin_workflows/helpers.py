"""S56 W4 — helpers.py part of admin_workflows decomp.

Classes: .
Funcs: _bind_workflow_status, _instance_store, _event_store, _row_to_schema, _list_instances_filtered, _get_facade, _trigger_via_action_or_store, _wait_for_terminal.
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

from fastapi import HTTPException

from src.backend.entrypoints.base import dispatch_action

# Wave 6.5a: типы для type-hints импортируются через TYPE_CHECKING, чтобы
# не нарушать layer policy (entrypoints → infrastructure запрещено).
# Runtime-доступ к классам — через core.di.providers (lazy importlib).
from src.backend.schemas.workflow import WorkflowInstanceSchemaOut

# Wave 6.5a: ``WorkflowStatus`` нужен Pydantic'у на этапе построения
# схемы ``ListWorkflowsQuery`` (форвард-референс резолвится через
# модульный namespace), поэтому единожды резолвится через DI provider
# при импорте этого модуля. Это сохраняет статический check_layers.py
# чистым (нет AST-импорта infrastructure), но на runtime даёт
# конкретный enum.


def _bind_workflow_status() -> Any:
    from src.backend.core.di.providers import get_workflow_status_enum_provider

    return get_workflow_status_enum_provider()


WorkflowStatus = _bind_workflow_status()


def _instance_store() -> Any:
    """Ленивый singleton :class:`WorkflowInstanceStore` через DI provider."""
    from src.backend.core.di.providers import get_workflow_state_store_provider

    return get_workflow_state_store_provider()()


def _event_store() -> Any:
    """Ленивый singleton :class:`WorkflowEventStore` через DI provider."""
    from src.backend.core.di.providers import get_workflow_event_store_provider

    return get_workflow_event_store_provider()()


def _row_to_schema(row: Any) -> WorkflowInstanceSchemaOut:
    """DTO-строка store'а → Pydantic-схему."""
    last_error: str | None = None
    if row.snapshot_state and isinstance(row.snapshot_state, dict):
        raw_err = row.snapshot_state.get("last_error")
        if isinstance(raw_err, str):
            last_error = raw_err

    return WorkflowInstanceSchemaOut(
        id=row.id,
        workflow_name=row.workflow_name,
        route_id=row.route_id,
        status=row.status,
        current_version=row.current_version,
        last_event_seq=row.last_event_seq,
        next_attempt_at=row.next_attempt_at,
        locked_by=row.locked_by,
        locked_until=row.locked_until,
        tenant_id=row.tenant_id,
        input_payload=row.input_payload,
        created_at=row.created_at,
        updated_at=row.updated_at,
        finished_at=row.finished_at,
        last_error=last_error,
    )


async def _list_instances_filtered(
    status_filter: WorkflowStatus | None,
    workflow_name: str | None,
    tenant_id: str | None,
    limit: int,
) -> list[Any]:
    """Читает header'ы с фильтрами напрямую (без обёртки store'а).

    ``WorkflowInstanceStore.list_pending`` заточен под worker-poll
    (фильтрует по eligibility), админский list должен показывать
    ВСЕ инстансы — включая ``succeeded``/``failed``/``cancelled``.
    """
    from sqlalchemy import select

    # Wave 6.5a: ORM-класс и session_manager — через DI providers.
    from src.backend.core.di.providers import (
        get_workflow_instance_model_provider,
        get_workflow_main_session_provider,
        get_workflow_state_row_class_provider,
    )

    WorkflowInstance = get_workflow_instance_model_provider()
    main_session_manager = get_workflow_main_session_provider()
    WorkflowInstanceRow = get_workflow_state_row_class_provider()

    async with main_session_manager.create_session() as session:
        stmt = select(WorkflowInstance)
        if status_filter is not None:
            stmt = stmt.where(WorkflowInstance.status == status_filter)
        if workflow_name is not None:
            stmt = stmt.where(WorkflowInstance.workflow_name == workflow_name)
        if tenant_id is not None:
            stmt = stmt.where(WorkflowInstance.tenant_id == tenant_id)
        stmt = stmt.order_by(WorkflowInstance.created_at.desc()).limit(limit)

        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [WorkflowInstanceRow.from_orm(r) for r in rows]


async def _trigger_via_action_or_store(
    *, store: Any, workflow_name: str, route_id: str, payload: dict[str, Any]
) -> UUID:
    """Создаёт workflow-инстанс.

    Приоритет:
        1. Если в ``action_handler_registry`` зарегистрирован action
           ``workflows.trigger`` — делегируем через
           :func:`dispatch_action`.
        2. Fallback — прямой вызов ``store.create()``.
    """
    from src.backend.dsl.commands.registry import action_handler_registry

    if action_handler_registry.is_registered("workflows.trigger"):
        result = await dispatch_action(
            action="workflows.trigger",
            payload={
                "workflow_name": workflow_name,
                "route_id": route_id,
                "payload": payload,
            },
            source="rest-admin",
        )
        if isinstance(result, dict) and "id" in result:
            return UUID(str(result["id"]))
        if isinstance(result, UUID):
            return result
        return UUID(str(result))

    return await store.create(
        workflow_name=workflow_name, route_id=route_id, input_payload=payload
    )


async def _wait_for_terminal(
    *, store: Any, instance_id: UUID, timeout_s: int, poll_interval_s: float = 2.0
) -> Any:
    """Блокирующее ожидание terminal-статуса через polling."""
    import asyncio

    terminal = {
        WorkflowStatus.succeeded,
        WorkflowStatus.failed,
        WorkflowStatus.cancelled,
    }
    deadline = datetime.now(UTC).timestamp() + timeout_s

    while True:
        row = await store.get(instance_id)
        if row is None:
            raise HTTPException(
                status_code=410, detail=f"Workflow instance '{instance_id}' disappeared"
            )
        if row.status in terminal:
            return row
        if datetime.now(UTC).timestamp() >= deadline:
            return row
        await asyncio.sleep(poll_interval_s)
