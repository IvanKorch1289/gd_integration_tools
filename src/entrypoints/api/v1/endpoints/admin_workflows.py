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

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, TypeAdapter

from src.entrypoints.api.generator.actions import ActionRouterBuilder, ActionSpec
from src.entrypoints.base import dispatch_action
from src.infrastructure.database.models.workflow_instance import WorkflowStatus
from src.infrastructure.workflow.event_store import WorkflowEventStore
from src.infrastructure.workflow.state_store import (
    WorkflowInstanceRow,
    WorkflowInstanceStore,
)
from src.schemas.workflow import (
    WorkflowCancelRequest,
    WorkflowEventSchemaOut,
    WorkflowInstanceDetailSchemaOut,
    WorkflowInstanceRef,
    WorkflowInstanceSchemaOut,
)
from src.workflows.registry import workflow_registry

__all__ = ("router",)

_logger = logging.getLogger("admin.workflows")


# --- Lazy singletons -------------------------------------------------------


def _instance_store() -> WorkflowInstanceStore:
    """Ленивый singleton :class:`WorkflowInstanceStore`."""
    return WorkflowInstanceStore()


def _event_store() -> WorkflowEventStore:
    """Ленивый singleton :class:`WorkflowEventStore`."""
    return WorkflowEventStore()


def _row_to_schema(row: WorkflowInstanceRow) -> WorkflowInstanceSchemaOut:
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


# --- Низкоуровневые SQL-хелперы --------------------------------------------


async def _list_instances_filtered(
    status_filter: WorkflowStatus | None,
    workflow_name: str | None,
    tenant_id: str | None,
    limit: int,
) -> list[WorkflowInstanceRow]:
    """Читает header'ы с фильтрами напрямую (без обёртки store'а).

    ``WorkflowInstanceStore.list_pending`` заточен под worker-poll
    (фильтрует по eligibility), админский list должен показывать
    ВСЕ инстансы — включая ``succeeded``/``failed``/``cancelled``.
    """
    from sqlalchemy import select

    from src.infrastructure.database.models.workflow_instance import WorkflowInstance
    from src.infrastructure.database.session_manager import main_session_manager

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


# --- Schemas ---------------------------------------------------------------


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
        default=False,
        description="Ждать завершения (polling до terminal или timeout).",
    )
    timeout_s: int = Field(
        default=30, ge=1, le=600, description="Timeout ожидания (только при wait=True)."
    )


class TriggerBody(BaseModel):
    """Тело trigger-эндпоинта (произвольный payload)."""

    model_config = {"extra": "allow"}


# --- Service facade --------------------------------------------------------


class _AdminWorkflowsFacade:
    """Адаптер над WorkflowInstanceStore + WorkflowEventStore + registry."""

    async def list_workflows(
        self,
        *,
        status_filter: WorkflowStatus | None = None,
        workflow_name: str | None = None,
        tenant_id: str | None = None,
        limit: int = 50,
    ) -> list[WorkflowInstanceSchemaOut]:
        rows = await _list_instances_filtered(
            status_filter=status_filter,
            workflow_name=workflow_name,
            tenant_id=tenant_id,
            limit=limit,
        )
        return [_row_to_schema(r) for r in rows]

    async def get_workflow(
        self, *, instance_id: UUID
    ) -> WorkflowInstanceDetailSchemaOut:
        row = await _instance_store().get(instance_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Workflow instance '{instance_id}' not found",
            )

        base = _row_to_schema(row)
        events_rows = await _event_store().read_events(
            workflow_id=instance_id, after_seq=0, limit=1000
        )
        events = [
            WorkflowEventSchemaOut(
                seq=e.seq,
                workflow_id=e.workflow_id,
                event_type=e.event_type,
                payload=e.payload,
                step_name=e.step_name,
                occurred_at=e.occurred_at,
            )
            for e in events_rows
        ]

        return WorkflowInstanceDetailSchemaOut(
            **base.model_dump(), snapshot_state=row.snapshot_state, events=events
        )

    async def get_events(
        self, *, instance_id: UUID, after_seq: int = 0, limit: int = 100
    ) -> list[WorkflowEventSchemaOut]:
        row = await _instance_store().get(instance_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Workflow instance '{instance_id}' not found",
            )

        events_rows = await _event_store().read_events(
            workflow_id=instance_id, after_seq=after_seq, limit=limit
        )
        return [
            WorkflowEventSchemaOut(
                seq=e.seq,
                workflow_id=e.workflow_id,
                event_type=e.event_type,
                payload=e.payload,
                step_name=e.step_name,
                occurred_at=e.occurred_at,
            )
            for e in events_rows
        ]

    async def retry_workflow(self, *, instance_id: UUID) -> dict[str, Any]:
        store = _instance_store()
        row = await store.get(instance_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Workflow instance '{instance_id}' not found",
            )

        terminal = {WorkflowStatus.succeeded, WorkflowStatus.cancelled}
        if row.status in terminal:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot retry workflow in terminal status '{row.status.value}'",
            )

        new_status = (
            WorkflowStatus.pending
            if row.status == WorkflowStatus.failed
            else row.status
        )
        await store.update_status(
            workflow_id=instance_id,
            status=new_status,
            next_attempt_at=datetime.now(timezone.utc),
        )
        _logger.info(
            "retry triggered: workflow_id=%s prev_status=%s",
            instance_id,
            row.status.value,
        )
        return {
            "status": "accepted",
            "instance_id": str(instance_id),
            "previous_status": row.status.value,
            "new_status": new_status.value,
        }

    async def cancel_workflow(
        self, *, instance_id: UUID, reason: str | None = None
    ) -> dict[str, Any]:
        store = _instance_store()
        row = await store.get(instance_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Workflow instance '{instance_id}' not found",
            )

        terminal = {
            WorkflowStatus.succeeded,
            WorkflowStatus.failed,
            WorkflowStatus.cancelled,
        }
        if row.status in terminal:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot cancel workflow in terminal status '{row.status.value}'",
            )

        await store.update_status(
            workflow_id=instance_id,
            status=WorkflowStatus.cancelling,
            next_attempt_at=datetime.now(timezone.utc),
            error=(f"cancelled: {reason}" if reason else None),
        )
        _logger.info(
            "cancel requested: workflow_id=%s reason=%s", instance_id, reason
        )
        return {
            "status": "accepted",
            "instance_id": str(instance_id),
            "new_status": WorkflowStatus.cancelling.value,
            "reason": reason,
        }

    async def resume_workflow(self, *, instance_id: UUID) -> dict[str, Any]:
        store = _instance_store()
        row = await store.get(instance_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Workflow instance '{instance_id}' not found",
            )
        if row.status != WorkflowStatus.paused:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot resume workflow in status '{row.status.value}' "
                    "(only 'paused' is resumable)"
                ),
            )

        await store.update_status(
            workflow_id=instance_id,
            status=WorkflowStatus.pending,
            next_attempt_at=datetime.now(timezone.utc),
        )
        _logger.info("resume triggered: workflow_id=%s", instance_id)
        return {
            "status": "accepted",
            "instance_id": str(instance_id),
            "new_status": WorkflowStatus.pending.value,
        }

    async def trigger_workflow(
        self,
        *,
        workflow_name: str,
        wait: bool = False,
        timeout_s: int = 30,
        **payload: Any,
    ) -> WorkflowInstanceRef:
        descriptor = workflow_registry.get(workflow_name)
        if descriptor is None:
            raise HTTPException(
                status_code=404, detail=f"Workflow '{workflow_name}' not registered"
            )

        route_id = workflow_registry.get_route_id(workflow_name)
        if route_id is None:
            raise HTTPException(
                status_code=500,
                detail=f"Workflow '{workflow_name}' missing route_id binding",
            )

        if descriptor.input_schema is not None:
            try:
                validated = descriptor.input_schema.model_validate(payload)
                payload = validated.model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=422, detail=f"Payload validation failed: {exc}"
                ) from exc

        store = _instance_store()
        instance_id = await _trigger_via_action_or_store(
            store=store,
            workflow_name=workflow_name,
            route_id=route_id,
            payload=payload,
        )
        _logger.info(
            "workflow triggered: name=%s instance_id=%s wait=%s",
            workflow_name,
            instance_id,
            wait,
        )

        row = await store.get(instance_id)
        if row is None:
            raise HTTPException(
                status_code=500,
                detail="Created instance disappeared (race condition)",
            )

        if wait:
            row = await _wait_for_terminal(
                store=store, instance_id=instance_id, timeout_s=timeout_s
            )

        last_error: str | None = None
        if row.snapshot_state and isinstance(row.snapshot_state, dict):
            raw_err = row.snapshot_state.get("last_error")
            if isinstance(raw_err, str):
                last_error = raw_err

        return WorkflowInstanceRef(
            id=row.id,
            workflow_name=row.workflow_name,
            status=row.status,
            created_at=row.created_at,
            result=(
                row.snapshot_state.get("exchange_snapshot")
                if (
                    row.status == WorkflowStatus.succeeded
                    and isinstance(row.snapshot_state, dict)
                )
                else None
            ),
            error=last_error if row.status == WorkflowStatus.failed else None,
        )


_FACADE = _AdminWorkflowsFacade()


def _get_facade() -> _AdminWorkflowsFacade:
    return _FACADE


# --- Helpers ---------------------------------------------------------------


async def _trigger_via_action_or_store(
    *,
    store: WorkflowInstanceStore,
    workflow_name: str,
    route_id: str,
    payload: dict[str, Any],
) -> UUID:
    """Создаёт workflow-инстанс.

    Приоритет:
        1. Если в ``action_handler_registry`` зарегистрирован action
           ``workflows.trigger`` — делегируем через
           :func:`dispatch_action`.
        2. Fallback — прямой вызов ``store.create()``.
    """
    from src.dsl.commands.registry import action_handler_registry

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
    *,
    store: WorkflowInstanceStore,
    instance_id: UUID,
    timeout_s: int,
    poll_interval_s: float = 2.0,
) -> WorkflowInstanceRow:
    """Блокирующее ожидание terminal-статуса через polling."""
    import asyncio

    terminal = {
        WorkflowStatus.succeeded,
        WorkflowStatus.failed,
        WorkflowStatus.cancelled,
    }
    deadline = datetime.now(timezone.utc).timestamp() + timeout_s

    while True:
        row = await store.get(instance_id)
        if row is None:
            raise HTTPException(
                status_code=410,
                detail=f"Workflow instance '{instance_id}' disappeared",
            )
        if row.status in terminal:
            return row
        if datetime.now(timezone.utc).timestamp() >= deadline:
            return row
        await asyncio.sleep(poll_interval_s)


def input_schema_json(schema: Any) -> dict[str, Any] | None:
    """Возвращает JSON-Schema Pydantic-модели или ``None``.

    Используется в MCP auto-export (``workflow_tools.py``) для
    формирования ``inputSchema`` MCP tool'а.
    """
    if schema is None:
        return None
    try:
        return TypeAdapter(schema).json_schema()
    except Exception:  # noqa: BLE001
        return None


# --- Router ----------------------------------------------------------------


router = APIRouter(tags=["Admin · Workflows"])
builder = ActionRouterBuilder(router)

common_tags = ("Admin · Workflows",)


builder.add_actions(
    [
        ActionSpec(
            name="admin_list_workflows",
            method="GET",
            path="/workflows",
            summary="Список durable workflows с фильтрацией",
            service_getter=_get_facade,
            service_method="list_workflows",
            query_model=ListWorkflowsQuery,
            argument_aliases={"status": "status_filter"},
            response_model=list[WorkflowInstanceSchemaOut],
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_get_workflow",
            method="GET",
            path="/workflows/{instance_id}",
            summary="Детальная информация о workflow-инстансе",
            service_getter=_get_facade,
            service_method="get_workflow",
            path_model=WorkflowInstanceIdPath,
            response_model=WorkflowInstanceDetailSchemaOut,
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_get_workflow_events",
            method="GET",
            path="/workflows/{instance_id}/events",
            summary="Paginated event log workflow'а",
            service_getter=_get_facade,
            service_method="get_events",
            path_model=WorkflowInstanceIdPath,
            query_model=EventsQuery,
            response_model=list[WorkflowEventSchemaOut],
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_retry_workflow",
            method="POST",
            path="/workflows/{instance_id}/retry",
            summary="Форсированный retry workflow'а",
            status_code=status.HTTP_202_ACCEPTED,
            service_getter=_get_facade,
            service_method="retry_workflow",
            path_model=WorkflowInstanceIdPath,
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_cancel_workflow",
            method="POST",
            path="/workflows/{instance_id}/cancel",
            summary="Отмена workflow'а (graceful)",
            status_code=status.HTTP_202_ACCEPTED,
            service_getter=_get_facade,
            service_method="cancel_workflow",
            path_model=WorkflowInstanceIdPath,
            body_model=WorkflowCancelRequest,
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_resume_workflow",
            method="POST",
            path="/workflows/{instance_id}/resume",
            summary="Возобновить paused workflow",
            status_code=status.HTTP_202_ACCEPTED,
            service_getter=_get_facade,
            service_method="resume_workflow",
            path_model=WorkflowInstanceIdPath,
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_trigger_workflow",
            method="POST",
            path="/workflows/trigger/{workflow_name}",
            summary="Запустить workflow по имени",
            status_code=status.HTTP_202_ACCEPTED,
            service_getter=_get_facade,
            service_method="trigger_workflow",
            path_model=WorkflowNamePath,
            query_model=TriggerQuery,
            body_model=TriggerBody,
            response_model=WorkflowInstanceRef,
            tags=common_tags,
        ),
    ]
)
