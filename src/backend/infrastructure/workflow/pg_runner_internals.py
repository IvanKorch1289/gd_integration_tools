"""Внутренние store-helpers для :class:`PgRunnerWorkflowBackend` (Sprint 4 К3-D §5).

Минимально-достаточный API инкапсулирует те ~5 методов,
которые реально нужны pg_runner-backend'у. Это:

* :meth:`WorkflowInstanceStore.create` — создать инстанс +
  ``created`` event (one-shot транзакция).
* :meth:`WorkflowInstanceStore.get` — header-запись (DTO).
* :meth:`WorkflowInstanceStore.update_status` — terminal/intermediate переход.
* :meth:`WorkflowEventStore.append` — append-only event log.

После Sprint 4 К3-D шаг 6 удаляются 4 deprecated-файла
(``state.py`` / ``state_store.py`` / ``event_store.py`` / ``state_projector.py``).
Этот модуль — package-private (НЕ re-export из ``__init__.py``);
единственный потребитель — ``pg_runner_backend.py``.

Архитектурное обоснование:
    * pg-runner stack — V11.1a legacy fallback до Wave D.2 (Temporal native).
      Удаление 4 файлов оставляет 1 узкий backend-адаптер с inline'нутыми
      хелперами вместо широкого fan-in API.
    * Mongo-проекция и advisory lock'и убраны — backend в режиме
      Adapter-only (без worker-полл'инга). Если когда-нибудь
      потребуется реактивировать durable runner, его нужно будет
      переписать поверх Temporal native.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update

from src.backend.infrastructure.database.models.workflow_event import (
    WorkflowEvent,
    WorkflowEventType,
)
from src.backend.infrastructure.database.models.workflow_instance import (
    WorkflowInstance,
    WorkflowStatus,
)
from src.backend.infrastructure.database.session_manager import main_session_manager

__all__ = (
    "WorkflowEventStore",
    "WorkflowInstanceRow",
    "WorkflowInstanceStore",
)


_logger = logging.getLogger("workflow.pg_runner_internals")


@dataclass(slots=True, frozen=True)
class WorkflowInstanceRow:
    """Immutable DTO header-записи workflow инстанса.

    Сохраняет совместимость с предыдущим ``state_store.WorkflowInstanceRow``
    (тот же набор полей) — `pg_runner_backend` и существующие тесты
    не требуют миграции.
    """

    id: UUID
    workflow_name: str
    route_id: str
    status: WorkflowStatus
    current_version: int
    last_event_seq: int | None
    snapshot_state: dict[str, Any] | None
    next_attempt_at: datetime | None
    locked_by: str | None
    locked_until: datetime | None
    tenant_id: str
    input_payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    @classmethod
    def from_orm(cls, obj: WorkflowInstance) -> "WorkflowInstanceRow":
        """Создаёт DTO из ORM-объекта."""
        return cls(
            id=obj.id,
            workflow_name=obj.workflow_name,
            route_id=obj.route_id,
            status=obj.status,
            current_version=int(obj.current_version),
            last_event_seq=(
                int(obj.last_event_seq) if obj.last_event_seq is not None else None
            ),
            snapshot_state=(dict(obj.snapshot_state) if obj.snapshot_state else None),
            next_attempt_at=obj.next_attempt_at,
            locked_by=obj.locked_by,
            locked_until=obj.locked_until,
            tenant_id=obj.tenant_id,
            input_payload=dict(obj.input_payload or {}),
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            finished_at=obj.finished_at,
        )


class WorkflowEventStore:
    """Append-only event store для pg-runner backend (узкий API)."""

    def __init__(self, session_manager: Any = None) -> None:
        self._sm = session_manager or main_session_manager

    async def append(
        self,
        workflow_id: UUID,
        event_type: WorkflowEventType,
        payload: dict[str, Any],
        step_name: str | None = None,
    ) -> int:
        """Добавить событие в log, вернуть его глобальный ``seq``.

        Побочный эффект — pg_notify-trigger на типах ``created`` /
        ``paused`` / ``resumed`` срабатывает автоматически (см. Alembic
        migration ``c3d4e5f6a7b8``).

        Args:
            workflow_id: UUID инстанса.
            event_type: Тип события.
            payload: JSON-сериализуемый dict.
            step_name: Имя DSL-шага (``None`` для instance-level).

        Returns:
            Глобальный ``seq`` созданного события.
        """
        async with self._sm.create_session() as session:
            async with self._sm.transaction(session):
                event = WorkflowEvent(
                    workflow_id=workflow_id,
                    event_type=event_type,
                    payload=dict(payload),
                    step_name=step_name,
                )
                session.add(event)
                await session.flush()
                seq = int(event.id)
                await session.execute(
                    update(WorkflowInstance)
                    .where(WorkflowInstance.id == workflow_id)
                    .values(last_event_seq=seq)
                )
        return seq


class WorkflowInstanceStore:
    """CRUD для header-таблицы ``workflow_instances`` (узкий API)."""

    def __init__(
        self,
        session_manager: Any = None,
        event_store: WorkflowEventStore | None = None,
    ) -> None:
        self._sm = session_manager or main_session_manager
        self._events = event_store or WorkflowEventStore(session_manager=self._sm)

    async def create(
        self,
        workflow_name: str,
        route_id: str,
        input_payload: dict[str, Any],
        tenant_id: str | None = None,
    ) -> UUID:
        """Создать инстанс + append ``created`` event атомарно.

        Триггер ``trg_workflow_notify`` отправит ``pg_notify(
        'workflow_pending', <id>)`` — подписанные worker'ы получат
        сигнал.

        Args:
            workflow_name: Логическое имя workflow.
            route_id: DSL ``route_id`` (равен ``workflow_name`` для
                pg-runner-backend).
            input_payload: Immutable вход (включая Temporal-style
                ``__workflow_id`` / ``__task_queue``).
            tenant_id: Multi-tenant scope (``None`` → "default").

        Returns:
            UUID созданного инстанса.
        """
        instance_id = uuid4()
        resolved_tenant = tenant_id or "default"

        async with self._sm.create_session() as session:
            async with self._sm.transaction(session):
                instance = WorkflowInstance(
                    id=instance_id,
                    workflow_name=workflow_name,
                    route_id=route_id,
                    status=WorkflowStatus.pending,
                    current_version=1,
                    input_payload=dict(input_payload),
                    tenant_id=resolved_tenant,
                )
                session.add(instance)
                await session.flush()

                event = WorkflowEvent(
                    workflow_id=instance_id,
                    event_type=WorkflowEventType.created,
                    payload={
                        "workflow_name": workflow_name,
                        "route_id": route_id,
                        "input": dict(input_payload),
                        "tenant_id": resolved_tenant,
                    },
                    step_name=None,
                )
                session.add(event)
                await session.flush()
                seq = int(event.id)
                await session.execute(
                    update(WorkflowInstance)
                    .where(WorkflowInstance.id == instance_id)
                    .values(last_event_seq=seq)
                )

        return instance_id

    async def get(self, workflow_id: UUID) -> WorkflowInstanceRow | None:
        """Вернуть header-запись инстанса или ``None`` если не найдено."""
        async with self._sm.create_session() as session:
            stmt = select(WorkflowInstance).where(
                WorkflowInstance.id == workflow_id
            )
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            return WorkflowInstanceRow.from_orm(obj) if obj is not None else None

    async def update_status(
        self,
        workflow_id: UUID,
        status: WorkflowStatus,
        next_attempt_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        """Обновить статус инстанса (terminal — выставит ``finished_at``).

        Args:
            workflow_id: UUID инстанса.
            status: Новый статус.
            next_attempt_at: Время следующей попытки (``None`` — не менять).
            error: Опциональная строка ошибки (хранится в
                ``snapshot_state.last_error`` для UI).
        """
        terminal = {
            WorkflowStatus.succeeded,
            WorkflowStatus.failed,
            WorkflowStatus.cancelled,
        }

        values: dict[str, Any] = {"status": status}
        if next_attempt_at is not None:
            values["next_attempt_at"] = next_attempt_at
        if status in terminal:
            values["finished_at"] = datetime.now(timezone.utc)

        async with self._sm.create_session() as session:
            async with self._sm.transaction(session):
                if error is not None:
                    await self._merge_error_into_snapshot(
                        session, workflow_id=workflow_id, error=error
                    )
                await session.execute(
                    update(WorkflowInstance)
                    .where(WorkflowInstance.id == workflow_id)
                    .values(**values)
                )

    @staticmethod
    async def _merge_error_into_snapshot(
        session: Any, *, workflow_id: UUID, error: str
    ) -> None:
        """Подмешать ``last_error`` в ``snapshot_state`` без затирания других ключей."""
        stmt = select(WorkflowInstance.snapshot_state).where(
            WorkflowInstance.id == workflow_id
        )
        result = await session.execute(stmt)
        snapshot = result.scalar_one_or_none() or {}
        merged = dict(snapshot)
        merged["last_error"] = error
        await session.execute(
            update(WorkflowInstance)
            .where(WorkflowInstance.id == workflow_id)
            .values(snapshot_state=merged)
        )
