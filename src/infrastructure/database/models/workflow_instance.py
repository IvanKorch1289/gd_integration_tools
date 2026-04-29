"""ORM-модель инстанса durable workflow.

Таблица ``workflow_instances`` — header-запись для каждого запущенного
workflow. Хранит логический статус, версию spec, позицию в event log
(``last_event_seq``), опциональный snapshot, параметры locking'а (advisory
lock в Postgres) и ссылку на DSL route_id.

State-транзиции пишутся append-only в ``workflow_events``. Эта таблица
используется как быстрый индекс для worker'ов (``list_pending``) и для
быстрого отображения статуса — полный state восстанавливается через
``WorkflowState.replay(events)``.

См. также:
    * :mod:`app.infrastructure.database.models.workflow_event` — append-only
      event log с триггером pg_notify.
    * :mod:`app.infrastructure.workflow.state_store` — thin CRUD API.
    * :mod:`app.infrastructure.workflow.event_store` — append-only event API.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.migrations._compat import json_b, uuid_t
from src.infrastructure.database.models.base import BaseModel
from src.infrastructure.database.tenant_filter import TenantMixin

__all__ = ("WorkflowInstance", "WorkflowStatus")


class WorkflowStatus(str, enum.Enum):
    """Логические статусы инстанса workflow.

    * ``pending`` — создан, ожидает первого шага (worker ещё не подхватил).
    * ``running`` — активно выполняется worker'ом.
    * ``paused`` — приостановлен (ждёт внешнего события / таймера).
    * ``succeeded`` — успешно завершён.
    * ``failed`` — завершён с ошибкой (все ретраи исчерпаны).
    * ``cancelling`` — получен сигнал cancel, идёт graceful stop.
    * ``cancelled`` — отменён.
    * ``compensating`` — выполняются Saga-компенсации.
    """

    pending = "pending"
    running = "running"
    paused = "paused"
    succeeded = "succeeded"
    failed = "failed"
    cancelling = "cancelling"
    cancelled = "cancelled"
    compensating = "compensating"


class WorkflowInstance(BaseModel, TenantMixin):
    """Инстанс durable workflow.

    Attributes:
        id: UUID — глобально уникальный идентификатор инстанса.
        workflow_name: Логическое имя workflow (``orders.skb_flow`` и т.п.).
        route_id: DSL ``route_id`` из :class:`RouteRegistry` — определяет
            код, который будет выполняться.
        status: Текущий логический статус (см. :class:`WorkflowStatus`).
        current_version: Версия spec на момент последнего apply. Используется
            для детектирования hot-reload (worker при расхождении может
            либо продолжить на старой spec, либо принудительно перезапустить).
        last_event_seq: Максимальный seq применённого события — позволяет
            worker'у быстро замечать новые события без полного re-read.
        snapshot_state: Кэшированный dump :class:`WorkflowState` после
            периодической компакции event log'а (каждые N событий).
        next_attempt_at: Время, не раньше которого имеет смысл пытаться
            снова (для pause / retry / scheduled resume).
        locked_by: Идентификатор worker'а, держащего advisory lock.
        locked_until: Время истечения lease — для detection зависших workers.
        tenant_id: Мульти-тенантная изоляция (через :class:`TenantMixin`).
        input_payload: Immutable входной payload (копия из запроса API).
        finished_at: Время финального перехода в terminal-статус.
    """

    __tablename__ = "workflow_instances"
    # Служебная таблица — SQLAlchemy-Continuum history не нужен.
    __versioned__ = {"versioning": False}
    __table_args__ = {"comment": "Durable workflow instances"}

    # Переопределяем id — BaseModel использует int, для workflow нужен UUID
    # (stable cross-service identifier, безопасно раздавать наружу).
    id: Mapped[uuid.UUID] = mapped_column(
        uuid_t(), primary_key=True, default=uuid.uuid4
    )

    workflow_name: Mapped[str] = mapped_column(String(256), index=True)
    route_id: Mapped[str] = mapped_column(String(256), index=True)

    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(
            WorkflowStatus,
            name="workflow_status",
            native_enum=True,
            create_constraint=False,
            values_callable=lambda e: [x.value for x in e],
        ),
        default=WorkflowStatus.pending,
        server_default=WorkflowStatus.pending.value,
        index=True,
        nullable=False,
    )

    current_version: Mapped[int] = mapped_column(
        BigInteger, default=1, server_default="1", nullable=False
    )

    last_event_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    snapshot_state: Mapped[dict[str, Any] | None] = mapped_column(
        json_b(), nullable=True
    )

    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    input_payload: Mapped[dict[str, Any]] = mapped_column(
        json_b(), nullable=False, default=dict, server_default="{}"
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Переопределяем created_at/updated_at из BaseModel на timezone-aware,
    # чтобы в event log и в header была единая timezone семантика.
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
