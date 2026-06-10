"""S55 W3 — instance_store.py part of pg_runner_internals decomp.

Classes: WorkflowInstanceStore.
Funcs: .
"""
from __future__ import annotations

"""Внутренние store-helpers для workflow-стека (Sprint 4 К3-B §3).

Объединяет API, ранее разнесённое по 4 deprecated-модулям
(``state.py`` / ``state_store.py`` / ``event_store.py`` /
``state_projector.py``). Минимально-достаточный набор, необходимый:

* :class:`PgRunnerWorkflowBackend` — узкий create/get/cancel/await-completion
  адаптер поверх Postgres backend'а;
* :class:`DurableWorkflowRunner` (``runner.py``) — orchestration loop:
  ``list_pending``/``try_lock``/``read_events``/``replay`` →
  ``WorkflowState`` → ``append`` → ``unlock``;
* :class:`DSLStepExecutor` (``executor.py``) — пользуется
  ``WorkflowState.replay`` для resume-after-crash сценариев.

Sprint 4 К3-B §3 — удалены 4 legacy-файла (985 LOC), Mongo-проекция
(``state_projector.py``) убрана без замены: новый стек идёт на Temporal
native (см. :mod:`temporal_backend`), pg_runner оставлен legacy fallback.
"""

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.infrastructure.database.models.workflow_event import (
    WorkflowEvent,
    WorkflowEventType,
)
from src.backend.infrastructure.database.models.workflow_instance import (
    WorkflowInstance,
    WorkflowStatus,
)
from src.backend.infrastructure.database.session_manager import main_session_manager
from src.backend.infrastructure.logging.factory import get_logger

_logger = get_logger("workflow.pg_runner_internals")

# ─────────────────────────────── DTO ───────────────────────────────

@dataclass(slots=True, frozen=True)

class WorkflowInstanceStore:
    """CRUD для header-таблицы ``workflow_instances``."""

    def __init__(
        self, session_manager: Any = None, event_store: WorkflowEventStore | None = None
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
        """Создаёт инстанс + append ``created`` event атомарно."""
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

                await self._events.append_within_session(
                    session,
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

        return instance_id

    async def get(self, workflow_id: UUID) -> WorkflowInstanceRow | None:
        """Возвращает header-запись инстанса или ``None``."""
        async with self._sm.create_session() as session:
            stmt = select(WorkflowInstance).where(WorkflowInstance.id == workflow_id)
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            return WorkflowInstanceRow.from_orm(obj) if obj is not None else None

    async def list_pending(
        self, limit: int = 100, tenant_id: str | None = None
    ) -> list[WorkflowInstanceRow]:
        """Инстансы, готовые к обработке worker'ом."""
        now = datetime.now(UTC)
        eligible_statuses = (
            WorkflowStatus.pending,
            WorkflowStatus.running,
            WorkflowStatus.paused,
        )

        async with self._sm.create_session() as session:
            stmt = (
                select(WorkflowInstance)
                .where(WorkflowInstance.status.in_(eligible_statuses))
                .where(
                    or_(
                        WorkflowInstance.next_attempt_at.is_(None),
                        WorkflowInstance.next_attempt_at <= now,
                    )
                )
                .where(
                    or_(
                        WorkflowInstance.locked_until.is_(None),
                        WorkflowInstance.locked_until < now,
                    )
                )
                .order_by(WorkflowInstance.created_at.asc())
                .limit(limit)
            )
            if tenant_id is not None:
                stmt = stmt.where(WorkflowInstance.tenant_id == tenant_id)

            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [WorkflowInstanceRow.from_orm(r) for r in rows]

    async def try_lock(self, workflow_id: UUID, worker_id: str, ttl_s: int) -> bool:
        """Кооперативная блокировка инстанса за worker'ом."""
        lock_key = _advisory_lock_key(workflow_id)
        locked_until = datetime.now(UTC) + timedelta(seconds=ttl_s)

        async with self._sm.create_session() as session:
            async with self._sm.transaction(session):
                lock_result = await session.execute(
                    text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": lock_key}
                )
                acquired = bool(lock_result.scalar())
                if not acquired:
                    return False

                await session.execute(
                    update(WorkflowInstance)
                    .where(WorkflowInstance.id == workflow_id)
                    .where(
                        or_(
                            WorkflowInstance.locked_until.is_(None),
                            WorkflowInstance.locked_until < datetime.now(UTC),
                        )
                    )
                    .values(locked_by=worker_id, locked_until=locked_until)
                )
        return True

    async def unlock(self, workflow_id: UUID, worker_id: str) -> None:
        """Снимает lease-блокировку с инстанса."""
        async with self._sm.create_session() as session:
            async with self._sm.transaction(session):
                await session.execute(
                    update(WorkflowInstance)
                    .where(
                        and_(
                            WorkflowInstance.id == workflow_id,
                            WorkflowInstance.locked_by == worker_id,
                        )
                    )
                    .values(locked_by=None, locked_until=None)
                )

    async def update_status(
        self,
        workflow_id: UUID,
        status: WorkflowStatus,
        next_attempt_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        """Обновить статус инстанса (terminal — выставит ``finished_at``)."""
        terminal = {
            WorkflowStatus.succeeded,
            WorkflowStatus.failed,
            WorkflowStatus.cancelled,
        }

        values: dict[str, Any] = {"status": status}
        if next_attempt_at is not None:
            values["next_attempt_at"] = next_attempt_at
        if status in terminal:
            values["finished_at"] = datetime.now(UTC)

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
        session: AsyncSession, *, workflow_id: UUID, error: str
    ) -> None:
        """Подмешать ``last_error`` в ``snapshot_state`` без затирания ключей."""
        stmt = select(WorkflowInstance.snapshot_state).where(
            WorkflowInstance.id == workflow_id
        )
        result = await session.execute(stmt)
        snapshot = result.scalar_one_or_none() or {}
        merged = dict(snapshot)
        merged["last_error"] = error[:2048]
        await session.execute(
            update(WorkflowInstance)
            .where(WorkflowInstance.id == workflow_id)
            .values(snapshot_state=merged)
        )

