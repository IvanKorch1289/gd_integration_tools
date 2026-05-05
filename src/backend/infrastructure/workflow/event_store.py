"""Append-only event store для durable workflows.

:class:`WorkflowEventStore` предоставляет узкий API для работы с event log'ом:

* :meth:`append` — добавление события (любой state-transition).
* :meth:`read_events` — инкрементальное чтение для replay / worker poll.
* :meth:`latest_seq` — максимальный seq (cursor tip).
* :meth:`snapshot` — периодическая компакция: кэш materialized state в
  ``workflow_instances.snapshot_state`` + event ``snapshotted``.

Принципы:
    * Все state transitions пишутся как события — header-таблица только
      кэш для быстрых запросов.
    * События **immutable** — UPDATE/DELETE на уровне API запрещён.
    * ``append`` делает flush (не commit) — вызывающий код управляет
      транзакцией (обычно open session + append + update header + commit).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.workflow_event import (
    WorkflowEvent,
    WorkflowEventType,
)
from src.infrastructure.database.models.workflow_instance import WorkflowInstance
from src.infrastructure.database.session_manager import main_session_manager

__all__ = ("WorkflowEventRow", "WorkflowEventStore")


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
    def from_orm(cls, obj: WorkflowEvent) -> "WorkflowEventRow":
        """Создаёт DTO из ORM-объекта."""
        return cls(
            seq=int(obj.id),
            workflow_id=obj.workflow_id,
            event_type=obj.event_type,
            payload=dict(obj.payload or {}),
            step_name=obj.step_name,
            occurred_at=obj.occurred_at,
        )


class WorkflowEventStore:
    """Append-only event store поверх ``workflow_events``.

    По умолчанию использует главный ``main_session_manager``. Для кастомного
    session-маркера (например, в тестах или внешних БД) допустимо передать
    собственный ``session_manager``.
    """

    def __init__(self, session_manager: Any = None) -> None:
        self._sm = session_manager or main_session_manager

    async def append(
        self,
        workflow_id: UUID,
        event_type: WorkflowEventType,
        payload: dict[str, Any],
        step_name: str | None = None,
    ) -> int:
        """Добавляет событие в log, возвращает его глобальный ``seq``.

        Побочный эффект: если ``event_type`` триггерит pg_notify
        (``created``/``paused``/``resumed``) — соответствующий NOTIFY
        будет отправлен БД автоматически (см. Alembic migration
        ``c3d4e5f6a7b8``).

        Args:
            workflow_id: UUID инстанса.
            event_type: Тип события.
            payload: JSON-сериализуемый dict с данными события.
            step_name: Имя DSL-шага (``None`` для instance-level событий).

        Returns:
            Глобальный ``seq`` созданного события.
        """
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
        """Append в уже открытой сессии — для atomic-batch с header-updates.

        Вызывающий код отвечает за commit/rollback.
        """
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
        await session.flush()  # populate id (seq) без commit

        seq = int(event.id)
        # Header: обновляем last_event_seq атомарно в той же транзакции.
        await session.execute(
            update(WorkflowInstance)
            .where(WorkflowInstance.id == workflow_id)
            .values(last_event_seq=seq, updated_at=datetime.utcnow())
        )
        return seq

    async def read_events(
        self, workflow_id: UUID, after_seq: int = 0, limit: int = 1000
    ) -> list[WorkflowEventRow]:
        """Читает события ``seq > after_seq`` в порядке возрастания ``seq``.

        Используется:
            * При replay — полное чтение (``after_seq=0``).
            * При инкрементальной обработке worker'ом — с курсором.

        Args:
            workflow_id: UUID инстанса.
            after_seq: Нижняя граница (исключительно). ``0`` = с начала.
            limit: Верхний предел на размер batch'а.

        Returns:
            Список DTO (``list[WorkflowEventRow]``) — может быть пуст.
        """
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
        """Фиксирует snapshot state + event ``snapshotted``.

        Выполняется атомарно:
            1. UPDATE ``workflow_instances.snapshot_state`` = state.
            2. INSERT event ``snapshotted`` с ``payload={"at_seq": at_seq}``.

        Args:
            workflow_id: UUID инстанса.
            state: Сериализуемый dict с текущим :class:`WorkflowState`.
            at_seq: Seq последнего события, вошедшего в snapshot (все
                события с ``seq > at_seq`` должны быть replayed поверх
                snapshot'а).
        """
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
