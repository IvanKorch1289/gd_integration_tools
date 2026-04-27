"""Admin REST API для durable workflows (IL-WF1.5).

Endpoints для on-call инженеров и UI:

    * ``GET    /api/v1/admin/workflows`` — list + фильтрация.
    * ``GET    /api/v1/admin/workflows/{id}`` — header + event log.
    * ``GET    /api/v1/admin/workflows/{id}/events`` — paginated events.
    * ``POST   /api/v1/admin/workflows/{id}/retry`` — force retry.
    * ``POST   /api/v1/admin/workflows/{id}/cancel`` — graceful cancel.
    * ``POST   /api/v1/admin/workflows/{id}/resume`` — resume paused.
    * ``POST   /api/v1/admin/workflows/trigger/{name}`` — universal trigger.

Авторизация: эндпоинты монтируются под ``/admin`` — защищены
глобальным :class:`APIKeyMiddleware` (см.
``src/entrypoints/middlewares/api_key.py``). Отдельный RBAC/OPA
scope (``platform-admin``) — задача IL2.

Все методы async, все логи — через stdlib ``logging`` (structlog
конфигурируется глобально).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Query, status
from pydantic import TypeAdapter

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

router = APIRouter(tags=["Admin · Workflows"])


# --- Dependency-style getters (lazy singletons) -----------------------


def _instance_store() -> WorkflowInstanceStore:
    """Ленивый singleton :class:`WorkflowInstanceStore`.

    В IL-WF1.3 может быть заменён на ``svcs.get_service(...)`` — пока
    тривиальная фабрика без cross-cutting concerns.
    """
    return WorkflowInstanceStore()


def _event_store() -> WorkflowEventStore:
    """Ленивый singleton :class:`WorkflowEventStore`."""
    return WorkflowEventStore()


def _row_to_schema(row: WorkflowInstanceRow) -> WorkflowInstanceSchemaOut:
    """Преобразует DTO-строку store'а в Pydantic-схему.

    Отдельной утилитой — чтобы не дублировать в list/get/trigger.
    """
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


# --- Низкоуровневые SQL-хелперы ----------------------------------------


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


# --- Endpoints ---------------------------------------------------------


@router.get(
    "/workflows",
    response_model=list[WorkflowInstanceSchemaOut],
    summary="Список durable workflows с фильтрацией",
    description=(
        "Возвращает header-записи workflow-инстансов. Поддерживает "
        "фильтры по status / workflow_name / tenant_id. Сортировка — "
        "по created_at DESC (новые сверху). Лимит — 500."
    ),
)
async def list_workflows(
    status_filter: WorkflowStatus | None = Query(
        None, alias="status", description="Фильтр по статусу инстанса."
    ),
    workflow_name: str | None = Query(
        None, description="Фильтр по логическому имени workflow."
    ),
    tenant_id: str | None = Query(None, description="Фильтр по tenant scope."),
    limit: int = Query(50, ge=1, le=500, description="Максимум записей в ответе."),
) -> list[WorkflowInstanceSchemaOut]:
    """Получить список workflow-инстансов."""
    rows = await _list_instances_filtered(
        status_filter=status_filter,
        workflow_name=workflow_name,
        tenant_id=tenant_id,
        limit=limit,
    )
    return [_row_to_schema(r) for r in rows]


@router.get(
    "/workflows/{instance_id}",
    response_model=WorkflowInstanceDetailSchemaOut,
    summary="Детальная информация о workflow-инстансе",
    description=(
        "Возвращает header + полный event log инстанса. Для длинных "
        "log'ов (N > 500) используйте paginated endpoint "
        "``GET /workflows/{id}/events?after_seq=...``."
    ),
)
async def get_workflow(instance_id: UUID) -> WorkflowInstanceDetailSchemaOut:
    """Получить workflow с событиями."""
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


@router.get(
    "/workflows/{instance_id}/events",
    response_model=list[WorkflowEventSchemaOut],
    summary="Paginated event log workflow'а",
    description=(
        "Читает события ``seq > after_seq`` в порядке возрастания. "
        "Для полного log'а используйте cursor-пагинацию: повторяйте "
        "с ``after_seq = last.seq`` пока ответ не станет пустым."
    ),
)
async def get_workflow_events(
    instance_id: UUID,
    after_seq: int = Query(0, ge=0, description="Cursor — нижняя граница seq."),
    limit: int = Query(100, ge=1, le=1000, description="Максимум событий в batch'е."),
) -> list[WorkflowEventSchemaOut]:
    """Читать события workflow'а с курсором."""
    # Проверка существования (даём 404 вместо пустого списка для UX).
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


@router.post(
    "/workflows/{instance_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Форсированный retry workflow'а",
    description=(
        "Сбрасывает ``next_attempt_at = now()`` — инстанс будет "
        "подхвачен worker'ом при ближайшем poll. Применимо к статусам "
        "``pending`` / ``failed`` / ``paused``. Для ``succeeded`` "
        "/ ``cancelled`` возвращает 409."
    ),
)
async def retry_workflow(instance_id: UUID) -> dict[str, Any]:
    """Принудительный retry."""
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
            detail=(f"Cannot retry workflow in terminal status '{row.status.value}'"),
        )

    # Для failed — возвращаем в pending, чтобы worker его поднял.
    new_status = (
        WorkflowStatus.pending if row.status == WorkflowStatus.failed else row.status
    )
    await store.update_status(
        workflow_id=instance_id,
        status=new_status,
        next_attempt_at=datetime.now(timezone.utc),
    )
    _logger.info(
        "retry triggered: workflow_id=%s prev_status=%s", instance_id, row.status.value
    )
    return {
        "status": "accepted",
        "instance_id": str(instance_id),
        "previous_status": row.status.value,
        "new_status": new_status.value,
    }


@router.post(
    "/workflows/{instance_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Отмена workflow'а (graceful)",
    description=(
        "Переводит инстанс в статус ``cancelling``. Worker при "
        "очередном poll запустит Saga-компенсации и затем переведёт "
        "в ``cancelled``. Terminal-статусы неотменяемы (409)."
    ),
)
async def cancel_workflow(
    instance_id: UUID,
    body: WorkflowCancelRequest = Body(default_factory=WorkflowCancelRequest),
) -> dict[str, Any]:
    """Запрос на отмену workflow'а."""
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
            detail=(f"Cannot cancel workflow in terminal status '{row.status.value}'"),
        )

    await store.update_status(
        workflow_id=instance_id,
        status=WorkflowStatus.cancelling,
        next_attempt_at=datetime.now(timezone.utc),
        error=(f"cancelled: {body.reason}" if body.reason else None),
    )
    _logger.info("cancel requested: workflow_id=%s reason=%s", instance_id, body.reason)
    return {
        "status": "accepted",
        "instance_id": str(instance_id),
        "new_status": WorkflowStatus.cancelling.value,
        "reason": body.reason,
    }


@router.post(
    "/workflows/{instance_id}/resume",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Возобновить paused workflow",
    description=(
        "Применимо только к статусу ``paused`` — сбрасывает "
        "``next_attempt_at = now()``. Для остальных статусов — 409."
    ),
)
async def resume_workflow(instance_id: UUID) -> dict[str, Any]:
    """Возобновить paused workflow."""
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
        next_attempt_at=datetime.now(timezone.utc),
    )
    _logger.info("resume triggered: workflow_id=%s", instance_id)
    return {
        "status": "accepted",
        "instance_id": str(instance_id),
        "new_status": WorkflowStatus.pending.value,
    }


@router.post(
    "/workflows/trigger/{workflow_name}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=WorkflowInstanceRef,
    summary="Запустить workflow по имени",
    description=(
        "Универсальный trigger: находит workflow в реестре, валидирует "
        "payload (если у descriptor'а есть input_schema), создаёт "
        "инстанс и возвращает ref. При ``wait=True`` блокируется "
        "до terminal-статуса или timeout'а (polling каждые 2s)."
    ),
)
async def trigger_workflow(
    workflow_name: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    wait: bool = Query(
        False, description="Ждать завершения (polling до terminal или timeout)."
    ),
    timeout_s: int = Query(
        30,
        ge=1,
        le=600,
        description="Timeout ожидания (действует только при wait=True).",
    ),
) -> WorkflowInstanceRef:
    """Trigger workflow по имени."""
    descriptor = workflow_registry.get(workflow_name)
    if descriptor is None:
        raise HTTPException(
            status_code=404, detail=f"Workflow '{workflow_name}' not registered"
        )

    route_id = workflow_registry.get_route_id(workflow_name)
    if route_id is None:
        # Инвариант нарушен (descriptor есть, route_id нет) — defensive.
        raise HTTPException(
            status_code=500,
            detail=f"Workflow '{workflow_name}' missing route_id binding",
        )

    # Валидация payload через Pydantic (если задана схема).
    if descriptor.input_schema is not None:
        try:
            validated = descriptor.input_schema.model_validate(payload)
            # Сохраняем как dict для JSONB-поля.
            payload = validated.model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=422, detail=f"Payload validation failed: {exc}"
            ) from exc

    # Unified dispatch — пока делегируем в store напрямую; в IL-WF1.3
    # здесь будет ``dispatch_action(action="workflows.trigger", ...)``
    # для единообразия с прочими протоколами. Пока action не
    # зарегистрирован — вызов идёт через store, чтобы не падать
    # при trigger'е до wiring'а action-handler'а.
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
        # Race невозможен в том же соединении — defensive fallback.
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


# --- Helpers -----------------------------------------------------------


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
           :func:`dispatch_action` (единый путь для всех протоколов,
           включает audit/tracing).
        2. Fallback — прямой вызов ``store.create()`` (нужен до
           wiring'а action-handler'а в IL-WF1.3).
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
        # Handler должен вернуть {"id": UUID} или UUID напрямую.
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
    """Блокирующее ожидание terminal-статуса через polling.

    Postgres LISTEN на per-workflow канал возможен (см. ADR-031), но
    требует отдельного asyncpg-connection per request — тяжело для
    REST. Polling каждые 2s — приемлемый компромисс для MVP.
    """
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
                status_code=410, detail=f"Workflow instance '{instance_id}' disappeared"
            )
        if row.status in terminal:
            return row
        if datetime.now(timezone.utc).timestamp() >= deadline:
            return row  # Возвращаем последнее известное состояние.
        await asyncio.sleep(poll_interval_s)


# Expose утилиту для MCP auto-export (reuse без дублирования).
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
