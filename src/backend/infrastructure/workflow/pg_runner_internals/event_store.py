"""S55 W3 — event_store.py part of pg_runner_internals decomp.

Classes: WorkflowEventStore.
Funcs: _find_last_snapshot, _advisory_lock_key.
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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.domain.models.workflow_event import (
    WorkflowEvent,
    WorkflowEventType,
)
from src.backend.core.domain.models.workflow_instance import (
    WorkflowInstance,
)
from src.backend.infrastructure.database.session_manager import main_session_manager
from src.backend.infrastructure.logging.factory import get_logger

_logger = get_logger("workflow.pg_runner_internals")

# ─────────────────────────────── DTO ───────────────────────────────


@dataclass(slots=True, frozen=True)
class WorkflowEventStore:
    """Append-only event store для durable workflows."""

    def __init__(self, session_manager: Any = None) -> None:
        self._sm = session_manager or main_session_manager

    async def append(
        self,
        workflow_id: UUID,
        event_type: WorkflowEventType,
        payload: dict[str, Any],
        step_name: str | None = None,
    ) -> int:
        """Добавить событие в log, вернуть его глобальный ``seq``."""
        async with self._sm.create_session() as session:
            async with self._sm.transaction(session):
                seq = await self._append_within_session(
                    session,
                    workflow_id=workflow_id,
                    event_type=event_type,
                    payload=payload,
                    step_name=step_name,
                )
        return seq

    async def append_within_session(
        self,
        session: AsyncSession,
        *,
        workflow_id: UUID,
        event_type: WorkflowEventType,
        payload: dict[str, Any],
        step_name: str | None = None,
    ) -> int:
        """Append в уже открытой сессии — для atomic-batch с header-updates."""
        return await self._append_within_session(
            session,
            workflow_id=workflow_id,
            event_type=event_type,
            payload=payload,
            step_name=step_name,
        )

    async def _append_within_session(
        self,
        session: AsyncSession,
        *,
        workflow_id: UUID,
        event_type: WorkflowEventType,
        payload: dict[str, Any],
        step_name: str | None,
    ) -> int:
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
            .values(last_event_seq=seq, updated_at=datetime.now(UTC))
        )
        return seq

    async def read_events(
        self, workflow_id: UUID, after_seq: int = 0, limit: int = 1000
    ) -> list[WorkflowEventRow]:
        """Читает события ``seq > after_seq`` в порядке возрастания."""
        async with self._sm.create_session() as session:
            stmt = (
                select(WorkflowEvent)
                .where(WorkflowEvent.workflow_id == workflow_id)
                .where(WorkflowEvent.id > after_seq)
                .order_by(WorkflowEvent.id.asc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [WorkflowEventRow.from_orm(r) for r in rows]

    async def latest_seq(self, workflow_id: UUID) -> int:
        """Возвращает ``max(seq)`` для workflow. ``0`` если событий нет."""
        async with self._sm.create_session() as session:
            stmt = select(func.max(WorkflowEvent.id)).where(
                WorkflowEvent.workflow_id == workflow_id
            )
            result = await session.execute(stmt)
            value = result.scalar_one_or_none()
            return int(value) if value is not None else 0

    async def snapshot(
        self, workflow_id: UUID, state: dict[str, Any], at_seq: int
    ) -> None:
        """Фиксирует snapshot state + event ``snapshotted`` атомарно."""
        async with self._sm.create_session() as session:
            async with self._sm.transaction(session):
                await session.execute(
                    update(WorkflowInstance)
                    .where(WorkflowInstance.id == workflow_id)
                    .values(snapshot_state=dict(state))
                )
                await self._append_within_session(
                    session,
                    workflow_id=workflow_id,
                    event_type=WorkflowEventType.snapshotted,
                    payload={"at_seq": at_seq},
                    step_name=None,
                )


def _find_last_snapshot(events: list[WorkflowEventRow]) -> int | None:
    """Возвращает индекс последнего ``snapshotted`` события или ``None``."""
    for idx in range(len(events) - 1, -1, -1):
        if events[idx].event_type == WorkflowEventType.snapshotted:
            return idx
    return None


def _advisory_lock_key(workflow_id: UUID) -> int:
    """Детерминистический 64-bit int-ключ из UUID для pg_advisory_lock."""
    digest = hashlib.blake2b(workflow_id.bytes, digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=False) & 0x7FFFFFFFFFFFFFFF
