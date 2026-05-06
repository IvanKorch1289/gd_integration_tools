# DEPRECATED V16 Sprint 1 — будет удалён после Single-Entry refactor финала.
# Temporal native (infrastructure/workflow/temporal_*) заменяет state-machine.
# См. PLAN.md V16 §4 Sprint 1 Workflow Single-Entry refactor.
"""Thin CRUD-API для header-таблицы ``workflow_instances``.

:class:`WorkflowInstanceStore` инкапсулирует:

* :meth:`create` — регистрация нового инстанса + append ``created`` event
  атомарно в одной транзакции (срабатывает pg_notify trigger).
* :meth:`get` — чтение header-записи.
* :meth:`list_pending` — выборка инстансов, готовых к обработке worker'ами
  (статусы ``pending``/``running``/``paused``, с истёкшим ``next_attempt_at``
  и свободным lease'ом).
* :meth:`try_lock` / :meth:`unlock` — кооперативная блокировка через
  Postgres advisory lock + DB-fallback на ``locked_by``/``locked_until``.
* :meth:`update_status` — переход статуса инстанса (без записи event —
  вызывающий код (runner) отвечает за корреспондирующие append'ы).

Важно: все методы транзакционны. Для atomic append event + update header
предпочтительно использовать :class:`WorkflowEventStore` напрямую в
собственной сессии runner'а.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.infrastructure.database.models.workflow_event import WorkflowEventType
from src.backend.infrastructure.database.models.workflow_instance import (
    WorkflowInstance,
    WorkflowStatus,
)
from src.backend.infrastructure.database.session_manager import main_session_manager
from src.backend.infrastructure.workflow.event_store import WorkflowEventStore

__all__ = ("WorkflowInstanceRow", "WorkflowInstanceStore")


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


def _advisory_lock_key(workflow_id: UUID) -> int:
    """Детерминистический 64-битный int-ключ из UUID для pg_advisory_lock.

    Используется BLAKE2b-64 поверх bytes UUID. Signed 64-bit — Postgres
    принимает ``bigint`` (-2^63 .. 2^63-1); маскируем в положительный
    диапазон для безопасности.
    """
    digest = hashlib.blake2b(workflow_id.bytes, digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=False) & 0x7FFFFFFFFFFFFFFF


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
        """Создаёт инстанс + append ``created`` event в одной транзакции.

        Триггер ``trg_workflow_notify`` автоматически отправит
        ``pg_notify('workflow_pending', <id>)`` — worker'ы, подписанные
        через ``LISTEN``, получат сигнал.

        Args:
            workflow_name: Логическое имя workflow.
            route_id: DSL ``route_id`` из :class:`RouteRegistry`.
            input_payload: Immutable вход.
            tenant_id: Multi-tenant scope. ``None`` → "default".

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

        # Wave 9.2.2: проекция в Mongo для observability.
        await self._project_to_mongo(instance_id)
        return instance_id

    async def get(self, workflow_id: UUID) -> WorkflowInstanceRow | None:
        """Возвращает header-запись инстанса или ``None`` если не найдено."""
        async with self._sm.create_session() as session:
            stmt = select(WorkflowInstance).where(WorkflowInstance.id == workflow_id)
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            return WorkflowInstanceRow.from_orm(obj) if obj is not None else None

    async def list_pending(
        self, limit: int = 100, tenant_id: str | None = None
    ) -> list[WorkflowInstanceRow]:
        """Инстансы, готовые к обработке worker'ом.

        Фильтры:
            * ``status IN ('pending','running','paused')``.
            * ``next_attempt_at IS NULL OR next_attempt_at <= now()``.
            * ``locked_until IS NULL OR locked_until < now()`` (свободный
              lease, не держится другим worker'ом).
            * (опционально) ``tenant_id = :tenant_id``.

        Сортировка — по ``created_at`` (FIFO).
        """
        now = datetime.now(timezone.utc)
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
        """Кооперативная блокировка инстанса за worker'ом.

        Двухуровневая схема:
            1. ``pg_try_advisory_lock(hash(workflow_id))`` — session-level
               Postgres lock (автоматически снимется при разрыве соединения).
            2. При успехе — UPDATE ``locked_by``/``locked_until`` для
               visibility другим worker'ам (и timeout-detection).

        Args:
            workflow_id: UUID инстанса.
            worker_id: Идентификатор worker'а (hostname + pid, например).
            ttl_s: Длительность lease в секундах.

        Returns:
            ``True`` — lock получен, worker владеет инстансом.
            ``False`` — lock занят другим процессом.
        """
        lock_key = _advisory_lock_key(workflow_id)
        locked_until = datetime.now(timezone.utc) + timedelta(seconds=ttl_s)

        async with self._sm.create_session() as session:
            async with self._sm.transaction(session):
                # pg_try_advisory_xact_lock — session-level был бы надёжнее
                # (auto-release on disconnect), но требует удержания
                # connection'а. Для первой итерации используем transaction-
                # level; после commit lock снимается — безопасность
                # обеспечивается полем locked_until.
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
                            WorkflowInstance.locked_until < datetime.now(timezone.utc),
                        )
                    )
                    .values(locked_by=worker_id, locked_until=locked_until)
                )
        return True

    async def unlock(self, workflow_id: UUID, worker_id: str) -> None:
        """Снимает lease-блокировку с инстанса.

        Выполняет UPDATE только если ``locked_by = worker_id`` — не
        затирает чужой lock в случае, если предыдущий lease уже истёк и
        другой worker забрал инстанс.
        """
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
        """Обновляет статус инстанса + ``next_attempt_at`` (для scheduled
        resume / retry backoff).

        Terminal-статусы (``succeeded``/``failed``/``cancelled``) также
        выставляют ``finished_at = now()``. Запись события в event log —
        ответственность вызывающего кода (обычно runner'а).

        Args:
            workflow_id: UUID инстанса.
            status: Новый статус.
            next_attempt_at: Время следующей попытки (``None`` — не
                менять существующее значение).
            error: Опциональная строка с ошибкой — хранится в
                ``snapshot_state.last_error`` для видимости в UI (не
                затирает существующий snapshot — только подмешивается).
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

        # Wave 9.2.2: fire-and-forget Mongo-проекция (UI/observability).
        await self._project_to_mongo(workflow_id)

    async def _project_to_mongo(self, workflow_id: UUID) -> None:
        """Отправляет актуальное состояние в Mongo (fire-and-forget)."""
        try:
            from src.backend.infrastructure.workflow.state_projector import (
                get_workflow_state_projector,
            )

            row = await self.get(workflow_id)
            if row is None:
                return
            await get_workflow_state_projector().sync_fire_and_forget(
                workflow_id=row.id,
                snapshot_state=row.snapshot_state,
                status=row.status.value,
                route_id=row.route_id,
                tenant_id=row.tenant_id,
                workflow_name=row.workflow_name,
                updated_at=row.updated_at,
                finished_at=row.finished_at,
            )
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning(
                "WorkflowStateProjector hook failed: %s", exc
            )

    async def _merge_error_into_snapshot(
        self, session: AsyncSession, *, workflow_id: UUID, error: str
    ) -> None:
        """Подмешивает ``last_error`` в ``snapshot_state`` без
        перезаписи прочих полей."""
        stmt = select(WorkflowInstance.snapshot_state).where(
            WorkflowInstance.id == workflow_id
        )
        result = await session.execute(stmt)
        current = result.scalar_one_or_none()
        snapshot: dict[str, Any] = dict(current) if current else {}
        snapshot["last_error"] = error[:2048]

        await session.execute(
            update(WorkflowInstance)
            .where(WorkflowInstance.id == workflow_id)
            .values(snapshot_state=snapshot)
        )
