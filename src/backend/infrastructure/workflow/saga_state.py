"""Workflow saga state persistence (Sprint 21 W8, B-05 closure + S17 K-OPS-1 carryover).

Источник: PLAN.md V22.2 §4 + ADR-NEW-14 + B-05 closure (in-flight workflows lost).

Назначение:
    Persistent saga state для долгоиграющих workflow в PostgreSQL:
    * ``WorkflowState`` SQLAlchemy model — checkpoints + compensating actions.
    * ``WorkflowStateRepository`` — save / load / list_compensating CRUD.

Use cases:
    * Save checkpoint после каждого step → restore at retry с N+1.
    * Save compensating action в saga rollback.
    * list_compensating() — fetch incomplete sagas для compensation worker.

Совместим с RLS (S21 W1) — содержит ``tenant_id`` колонку. Композиционный
ключ ``(workflow_id, run_id)`` обеспечивает уникальность instance × execution.

См. также:
    * :mod:`src.backend.infrastructure.workflow.pg_runner_backend` — caller.
    * :mod:`src.backend.infrastructure.workflow.lite_temporal_backend` —
      SQLite builtin (Temporal SDK) уже handles dev_light persistence.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    String,
    TypeDecorator,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.backend.core.database.dialect_types import json_b
from src.backend.core.domain.models.base import BaseModel
from src.backend.core.tenancy.sqlalchemy_filter import TenantMixin


class _UUIDType(TypeDecorator[uuid.UUID]):
    """UUID column type с auto-conversion для SQLite (PG → native UUID).

    На PostgreSQL хранится как native UUID; на SQLite — как ``String(36)`` со
    стороны драйвера + Python ↔ ``str()`` conversion. Решает проблему aiosqlite,
    который не умеет binding native ``uuid.UUID``.
    """

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value) if isinstance(value, uuid.UUID) else str(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


def uuid_t() -> Any:
    """Локальный alias на :class:`_UUIDType` — dialect-aware UUID column."""
    return _UUIDType()


__all__ = ("WorkflowState", "WorkflowStateRepository", "WorkflowStateValue")


WorkflowStateValue = Literal["running", "completed", "compensating", "rolled_back"]


class WorkflowState(BaseModel, TenantMixin):
    """Persistent saga state record.

    Attributes:
        workflow_id: UUID workflow instance (FK soft — не constraint).
        run_id: Унаследованный execution run id (Temporal-совместимый;
            один workflow_id может иметь несколько runs при retry).
        step_index: Индекс последнего успешно завершённого step.
        compensating_actions: JSON-список компенсирующих действий (по
            BPMN/Saga модели), которые нужно выполнить при rollback.
        state: Текущее состояние саги (running/completed/compensating/rolled_back).
        tenant_id: RLS scope (через TenantMixin).
        result_payload: Результат успешного завершения (опц.).
        error_message: Сообщение последней ошибки (опц.).
    """

    __tablename__ = "workflow_state"
    __versioned__ = {"versioning": False}
    __table_args__ = (
        UniqueConstraint(
            "workflow_id", "run_id", name="uq_workflow_state_workflow_run"
        ),
        Index("ix_workflow_state_state_tenant", "state", "tenant_id"),
        {"comment": "Sprint 21 W8 — saga state persistence (B-05)"},
    )

    # Переопределяем int-id BaseModel на UUID для consistent saga key
    id: Mapped[uuid.UUID] = mapped_column(
        uuid_t(), primary_key=True, default=uuid.uuid4
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(uuid_t(), index=True, nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    step_index: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    compensating_actions: Mapped[list[Any]] = mapped_column(
        json_b(), nullable=False, default=list, server_default="[]"
    )
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="running", server_default="running"
    )
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(
        json_b(), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class WorkflowStateRepository:
    """CRUD-репозиторий для :class:`WorkflowState`.

    Args:
        session: AsyncSession через DI.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        *,
        workflow_id: uuid.UUID,
        run_id: str,
        step_index: int,
        compensating_actions: list[Any] | None = None,
        state: WorkflowStateValue = "running",
        tenant_id: str = "default",
        result_payload: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> WorkflowState:
        """Upsert state record по (workflow_id, run_id).

        Если запись существует — обновляет step_index/compensating/state.
        Иначе — INSERT.

        Returns:
            Сохранённый ``WorkflowState`` (refreshed from DB).
        """
        existing = await self._fetch_one(workflow_id, run_id)
        if existing is None:
            record = WorkflowState(
                workflow_id=workflow_id,
                run_id=run_id,
                step_index=step_index,
                compensating_actions=list(compensating_actions or []),
                state=state,
                tenant_id=tenant_id,
                result_payload=result_payload,
                error_message=error_message,
            )
            self._session.add(record)
            await self._session.flush()
            return record
        existing.step_index = step_index
        if compensating_actions is not None:
            existing.compensating_actions = list(compensating_actions)
        existing.state = state
        if result_payload is not None:
            existing.result_payload = result_payload
        if error_message is not None:
            existing.error_message = error_message
        await self._session.flush()
        return existing

    async def load(self, workflow_id: uuid.UUID, run_id: str) -> WorkflowState | None:
        """Возвращает state-record по составному ключу."""
        return await self._fetch_one(workflow_id, run_id)

    async def list_compensating(
        self, *, tenant_id: str | None = None, limit: int = 100
    ) -> list[WorkflowState]:
        """Возвращает saga'и в состоянии compensating (для compensation worker).

        Args:
            tenant_id: опц. фильтр (применяется в дополнение к RLS).
            limit: max количество записей.
        """
        stmt = select(WorkflowState).where(WorkflowState.state == "compensating")
        if tenant_id is not None:
            stmt = stmt.where(WorkflowState.tenant_id == tenant_id)
        stmt = stmt.order_by(WorkflowState.updated_at.asc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def signal_event(
        self, workflow_id: uuid.UUID, run_id: str, *, event: WorkflowStateValue
    ) -> WorkflowState | None:
        """Атомарный переход state через signal-event.

        Используется как primitive для saga lifecycle: running → compensating
        → rolled_back / completed.
        """
        record = await self._fetch_one(workflow_id, run_id)
        if record is None:
            return None
        record.state = event
        await self._session.flush()
        return record

    async def _fetch_one(
        self, workflow_id: uuid.UUID, run_id: str
    ) -> WorkflowState | None:
        stmt = select(WorkflowState).where(
            WorkflowState.workflow_id == workflow_id, WorkflowState.run_id == run_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
