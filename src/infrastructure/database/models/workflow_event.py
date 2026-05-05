"""Append-only event log durable workflow.

Таблица ``workflow_events`` — источник истины (event sourcing). Любой
state-transition workflow'а — новая запись. State восстанавливается через
fold events (см. :func:`WorkflowState.replay`).

Инварианты:
    * Записи **immutable** — UPDATE/DELETE запрещён на уровне приложения.
    * Глобальный BIGSERIAL ``seq`` — монотонно возрастающий, уникальный
      per-row. Worker'ы используют его как cursor.
    * INSERT на события ``created``/``paused``/``resumed`` триггерит
      ``pg_notify('workflow_pending', workflow_id)`` — см. Alembic migration.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.migrations._compat import json_b, uuid_t
from src.infrastructure.database.models.base import BaseModel

__all__ = ("WorkflowEvent", "WorkflowEventType")


class WorkflowEventType(str, enum.Enum):
    """Типы событий, записываемых в event log.

    Instance-level:
        * ``created`` — инстанс зарегистрирован (первое событие).
        * ``paused`` — приостановлен (ждёт external signal / таймера).
        * ``resumed`` — продолжен после паузы.
        * ``cancelled`` — отменён (terminal).
        * ``snapshotted`` — контрольная точка: state закэширован в
          ``workflow_instances.snapshot_state`` для оптимизации replay.

    Step-level (step_name обязателен):
        * ``step_started`` — начато выполнение шага.
        * ``step_finished`` — шаг успешно завершён.
        * ``step_failed`` — шаг упал (payload содержит ``error``, ``attempt``).
        * ``branch_taken`` — выбрана ветка в ``choice``/``switch``.
        * ``loop_iter`` — итерация цикла.
        * ``sub_spawned`` — запущен дочерний workflow.
        * ``sub_completed`` — дочерний workflow завершился.
        * ``compensated`` — выполнена Saga-компенсация.

    Backend-bridge (Wave D.1, ADR-045):
        * ``signal_received`` — внешний сигнал (Temporal-style); payload
          содержит ``{"signal_name": ..., "data": ...}``. Для PG-runner
          этот тип используется adapter'ом ``PgRunnerWorkflowBackend``,
          чтобы эмулировать ``WorkflowBackend.signal_workflow``.
    """

    created = "created"
    step_started = "step_started"
    step_finished = "step_finished"
    step_failed = "step_failed"
    branch_taken = "branch_taken"
    loop_iter = "loop_iter"
    sub_spawned = "sub_spawned"
    sub_completed = "sub_completed"
    paused = "paused"
    resumed = "resumed"
    cancelled = "cancelled"
    compensated = "compensated"
    snapshotted = "snapshotted"
    signal_received = "signal_received"


class WorkflowEvent(BaseModel):
    """Одна строка event log'а.

    Attributes:
        seq: BIGSERIAL — глобальный монотонный идентификатор события.
            Используется worker'ами как cursor для инкрементального чтения.
        workflow_id: FK на :class:`WorkflowInstance` (cascade delete).
        event_type: Тип события — см. :class:`WorkflowEventType`.
        payload: Произвольный JSON с данными события. Схема зависит от
            ``event_type`` (``step_finished`` → ``{"result": ...}`` и т.д.).
        step_name: Имя шага DSL (null для instance-level событий).
        occurred_at: Момент записи (timezone-aware).
    """

    __tablename__ = "workflow_events"
    # Append-only таблица — SQLAlchemy-Continuum versioning не нужен.
    __versioned__ = {"versioning": False}

    __table_args__ = (
        Index("ix_workflow_events_workflow_id_seq", "workflow_id", "id"),
        {"comment": "Append-only event log для durable workflows"},
    )

    # Отключаем унаследованные id/created_at/updated_at — для event log
    # используется BIGSERIAL seq как PK; created_at/updated_at бессмысленны
    # (события immutable, есть occurred_at).
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    @property
    def seq(self) -> int:
        """Alias к ``id`` — семантическое имя глобального cursor'а."""
        return self.id

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        uuid_t(),
        ForeignKey("workflow_instances.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    event_type: Mapped[WorkflowEventType] = mapped_column(
        Enum(
            WorkflowEventType,
            name="workflow_event_type",
            native_enum=True,
            create_constraint=False,
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
    )

    payload: Mapped[dict[str, Any]] = mapped_column(
        json_b(), nullable=False, default=dict, server_default="{}"
    )

    step_name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        nullable=False,
    )

    # BaseModel требует created_at/updated_at — для append-only они совпадают
    # с occurred_at. Переопределяем, чтобы были timezone-aware.
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
