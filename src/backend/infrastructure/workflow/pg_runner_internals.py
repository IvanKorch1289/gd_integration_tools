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

from __future__ import annotations

import hashlib
import logging
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

__all__ = (
    "WorkflowEventRow",
    "WorkflowEventStore",
    "WorkflowInstanceRow",
    "WorkflowInstanceStore",
    "WorkflowState",
)


_logger = logging.getLogger("workflow.pg_runner_internals")


# ─────────────────────────────── DTO ───────────────────────────────


@dataclass(slots=True, frozen=True)
class WorkflowEventRow:
    """Immutable DTO одной строки event log'а.

    Использование DTO (а не ORM-объекта) делает API независимым от
    сессии — row можно хранить, передавать между корутинами и т.п.
    """

    seq: int
    workflow_id: UUID
    event_type: WorkflowEventType
    payload: dict[str, Any]
    step_name: str | None
    occurred_at: datetime

    @classmethod
    def from_orm(cls, obj: WorkflowEvent) -> WorkflowEventRow:
        """Создаёт DTO из ORM-объекта."""
        return cls(
            seq=int(obj.id),
            workflow_id=obj.workflow_id,
            event_type=obj.event_type,
            payload=dict(obj.payload or {}),
            step_name=obj.step_name,
            occurred_at=obj.occurred_at,
        )


@dataclass(slots=True, frozen=True)
class WorkflowInstanceRow:
    """Immutable DTO header-записи workflow инстанса."""

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
    def from_orm(cls, obj: WorkflowInstance) -> WorkflowInstanceRow:
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


# ────────────────────────── Materialized state ──────────────────────


@dataclass
class WorkflowState:
    """Materialized state workflow инстанса.

    Fold поверх event log'а через :meth:`replay`. Чистая функция от
    events → state.
    """

    workflow_id: UUID
    workflow_name: str = ""
    current_step: int = 0
    step_history: list[str] = field(default_factory=list)
    branch_choices: dict[str, str] = field(default_factory=dict)
    loop_counters: dict[str, int] = field(default_factory=dict)
    exchange_snapshot: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    status: WorkflowStatus = WorkflowStatus.pending
    last_error: str | None = None
    child_workflows: list[str] = field(default_factory=list)

    @classmethod
    def replay(cls, events: list[WorkflowEventRow]) -> WorkflowState:
        """Fold событий в текущее состояние.

        Если среди событий встречается ``snapshotted``, стартуем с
        последнего snapshot'а и применяем только последующие события.

        Args:
            events: Список событий в порядке возрастания ``seq``.

        Returns:
            Materialized :class:`WorkflowState`.

        Raises:
            ValueError: Если передан пустой список или первое событие
                без snapshot'а не ``created``.
        """
        if not events:
            raise ValueError("cannot replay empty event list")

        snapshot_index = _find_last_snapshot(events)

        if snapshot_index is not None:
            snap_event = events[snapshot_index]
            state = cls._from_snapshot_payload(
                workflow_id=snap_event.workflow_id,
                snapshot=snap_event.payload.get("state", {}),
            )
            tail = events[snapshot_index + 1 :]
        else:
            first = events[0]
            if first.event_type != WorkflowEventType.created:
                raise ValueError(
                    "first event without snapshot must be 'created', "
                    f"got {first.event_type!r}"
                )
            state = cls(
                workflow_id=first.workflow_id,
                workflow_name=first.payload.get("workflow_name", ""),
            )
            state._apply(first)
            tail = events[1:]

        for ev in tail:
            state._apply(ev)
        return state

    @classmethod
    def replay_from_snapshot(
        cls,
        workflow_id: UUID,
        snapshot: dict[str, Any],
        tail_events: list[WorkflowEventRow],
    ) -> WorkflowState:
        """Rebuild state из snapshot'а + хвоста событий."""
        state = cls._from_snapshot_payload(workflow_id, snapshot)
        for ev in tail_events:
            state._apply(ev)
        return state

    def to_snapshot(self) -> dict[str, Any]:
        """Сериализует state в JSON-совместимый dict для ``snapshot``'а."""
        raw = asdict(self)
        raw["workflow_id"] = str(self.workflow_id)
        raw["status"] = self.status.value
        return raw

    @classmethod
    def _from_snapshot_payload(
        cls, workflow_id: UUID, snapshot: dict[str, Any]
    ) -> WorkflowState:
        """Восстанавливает state из результата :meth:`to_snapshot`."""
        status_raw = snapshot.get("status", WorkflowStatus.pending.value)
        try:
            status = WorkflowStatus(status_raw)
        except ValueError:
            status = WorkflowStatus.pending

        return cls(
            workflow_id=workflow_id,
            workflow_name=snapshot.get("workflow_name", ""),
            current_step=int(snapshot.get("current_step", 0)),
            step_history=list(snapshot.get("step_history", [])),
            branch_choices=dict(snapshot.get("branch_choices", {})),
            loop_counters=dict(snapshot.get("loop_counters", {})),
            exchange_snapshot=dict(snapshot.get("exchange_snapshot", {})),
            attempts=int(snapshot.get("attempts", 0)),
            status=status,
            last_error=snapshot.get("last_error"),
            child_workflows=list(snapshot.get("child_workflows", [])),
        )

    def _apply(self, event: WorkflowEventRow) -> None:
        """Применяет одно событие к текущему state'у (mutate in place)."""
        etype = event.event_type
        payload = event.payload or {}

        if etype == WorkflowEventType.created:
            self.workflow_name = payload.get("workflow_name", self.workflow_name)
            self.status = WorkflowStatus.pending

        elif etype == WorkflowEventType.step_started:
            self.status = WorkflowStatus.running
            self.attempts = int(payload.get("attempt", self.attempts + 1))

        elif etype == WorkflowEventType.step_finished:
            if event.step_name:
                self.step_history.append(event.step_name)
            self.current_step = int(payload.get("next_step", self.current_step + 1))
            self.attempts = 0
            exch = payload.get("exchange")
            if isinstance(exch, dict):
                self.exchange_snapshot = exch

        elif etype == WorkflowEventType.step_failed:
            self.last_error = str(payload.get("error", ""))[:2048]
            self.attempts = int(payload.get("attempt", self.attempts))

        elif etype == WorkflowEventType.branch_taken:
            name = payload.get("choice", event.step_name or "")
            branch = payload.get("branch", "")
            if name:
                self.branch_choices[name] = branch

        elif etype == WorkflowEventType.loop_iter:
            name = payload.get("loop", event.step_name or "")
            if name:
                self.loop_counters[name] = self.loop_counters.get(name, 0) + 1

        elif etype == WorkflowEventType.sub_spawned:
            child = payload.get("child_workflow_id")
            if child:
                self.child_workflows.append(str(child))

        elif etype == WorkflowEventType.paused:
            self.status = WorkflowStatus.paused

        elif etype == WorkflowEventType.resumed:
            self.status = WorkflowStatus.running

        elif etype == WorkflowEventType.cancelled:
            self.status = WorkflowStatus.cancelled

        elif etype == WorkflowEventType.compensated:
            self.status = WorkflowStatus.compensating


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


# ───────────────────────────── Event store ─────────────────────────


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
            .values(last_event_seq=seq, updated_at=datetime.utcnow())
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


# ──────────────────────────── Instance store ───────────────────────


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
