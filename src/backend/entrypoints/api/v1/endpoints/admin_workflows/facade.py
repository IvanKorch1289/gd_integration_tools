"""S56 W4 — facade.py part of admin_workflows decomp.

Classes: _AdminWorkflowsFacade.
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

from fastapi import HTTPException

from src.backend.core.logging import get_logger

# Wave 6.5a: типы для type-hints импортируются через TYPE_CHECKING, чтобы
# не нарушать layer policy (entrypoints → infrastructure запрещено).
# Runtime-доступ к классам — через core.di.providers (lazy importlib).
from src.backend.entrypoints.api.v1.endpoints.admin_workflows import helpers
from src.backend.schemas.workflow import (
    WorkflowEventSchemaOut,
    WorkflowInstanceDetailSchemaOut,
    WorkflowInstanceRef,
    WorkflowInstanceSchemaOut,
)
from src.backend.services.workflow import workflow_registry

WorkflowStatus: Any = helpers.WorkflowStatus
_list_instances_filtered = helpers._list_instances_filtered
_row_to_schema = helpers._row_to_schema
_instance_store = helpers._instance_store
_event_store = helpers._event_store
_trigger_via_action_or_store = helpers._trigger_via_action_or_store
_wait_for_terminal = helpers._wait_for_terminal
_logger = get_logger(__name__)

# Wave 6.5a: ``WorkflowStatus`` нужен Pydantic'у на этапе построения
# схемы ``ListWorkflowsQuery`` (форвард-референс резолвится через
# модульный namespace), поэтому единожды резолвится через DI provider
# при импорте этого модуля. Это сохраняет статический check_layers.py
# чистым (нет AST-импорта infrastructure), но на runtime даёт
# конкретный enum.


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
                status_code=404, detail=f"Workflow instance '{instance_id}' not found"
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
                status_code=404, detail=f"Workflow instance '{instance_id}' not found"
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
                status_code=404, detail=f"Workflow instance '{instance_id}' not found"
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
            next_attempt_at=datetime.now(UTC),
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
                status_code=404, detail=f"Workflow instance '{instance_id}' not found"
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
            next_attempt_at=datetime.now(UTC),
            error=(f"cancelled: {reason}" if reason else None),
        )
        _logger.info("cancel requested: workflow_id=%s reason=%s", instance_id, reason)
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
                status_code=404, detail=f"Workflow instance '{instance_id}' not found"
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
            next_attempt_at=datetime.now(UTC),
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
            except Exception as exc:
                raise HTTPException(
                    status_code=422, detail=f"Payload validation failed: {exc}"
                ) from exc

        store = _instance_store()
        instance_id = await _trigger_via_action_or_store(
            store=store, workflow_name=workflow_name, route_id=route_id, payload=payload
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
                status_code=500, detail="Created instance disappeared (race condition)"
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

    async def get_saga_history(
        self, *, workflow_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Возвращает timeline saga events для workflow_id (compensation only)."""
        from src.backend.services.workflows.saga_history import get_saga_history as _get

        records = await _get(workflow_id, limit=limit)
        return [
            {
                "event_id": r.event_id,
                "event_type": r.event_type,
                "workflow_id": r.workflow_id,
                "tenant_id": r.tenant_id,
                "payload": r.payload,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "duration_ms": r.duration_ms,
            }
            for r in records
        ]


_FACADE = _AdminWorkflowsFacade()


def _get_facade() -> _AdminWorkflowsFacade:
    return _FACADE
