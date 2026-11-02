# ruff: noqa: S311 — false positive (non-cryptographic random: backoff/load balancing/sampling)

"""Durable workflow runner — background execution driver для IL-WF1.

Архитектура (ADR-031):

    ┌───────────────────────────────────────────────────┐
    │ DurableWorkflowRunner                             │
    │                                                   │
    │  1) asyncpg LISTEN 'workflow_pending'             │
    │  2) backup polling каждые 30s (safety net)        │
    │  3) для каждого pending instance:                 │
    │     a) try_lock (advisory lock + DB lease)        │
    │     b) replay events → WorkflowState              │
    │     c) execute next step(s) из route spec         │
    │     d) append events (step_started / step_finished│
    │        / paused / etc.)                           │
    │     e) unlock                                     │
    │                                                   │
    └───────────────────────────────────────────────────┘

Ключевая идея — runner НЕ импортирует DurableWorkflowProcessor
(который появится в IL-WF1.3). Вместо этого runner получает
``step_executor`` callable — функцию, которая знает как выполнять
один step и возвращать результат + метаданные для event-log'а.

Это даёт чистое разделение ответственности:
    * runner = orchestration (pick-up instance, lock, read state,
      dispatch to executor, record events, schedule next attempt).
    * step executor = execution details (DSL processors / control
      flow / sub-workflow spawn) — реализуется в IL-WF1.3.

Unit-testable без Postgres: pluggable `InstanceSource` + `StateStore` +
`EventStore` + `StepExecutor`.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from src.backend.core.domain.models.workflow_event import WorkflowEventType
from src.backend.core.domain.models.workflow_instance import WorkflowStatus
from src.backend.core.logging import get_logger
from src.backend.core.observability.workflow_sla import (
    classify_sla_breach,
    record_workflow_sla_compliance,
)
from src.backend.core.utils.task_registry import get_task_registry
from src.backend.infrastructure.messaging.dlq_base import DLQWriter
from src.backend.infrastructure.observability.otel.setup import (
    record_workflow_compensation,
    record_workflow_status,
    record_workflow_step_duration,
    record_workflow_step_retries,
)
from src.backend.infrastructure.workflow.pg_runner_internals import (
    PHASE_CANCELLED,
    PHASE_FAILED,
    PHASE_STARTED,
    PHASE_SUCCEEDED,
    WorkflowEventRow,
    WorkflowEventStore,
    WorkflowInstanceRow,
    WorkflowInstanceStore,
    WorkflowState,
    emit_step_audit,
    step_start_logged,
    step_terminal_logged,
)
from src.backend.infrastructure.workflow.pg_runner_internals.workflow_dlq import (
    WorkflowDLQPublisher,
)
from src.backend.infrastructure.workflow.registry import workflow_registry

__all__ = (
    "DurableWorkflowRunner",
    "RunnerConfig",
    "StepExecutor",
    "StepResult",
    "idempotency_key",
)


_logger = get_logger("workflow.runner")


def idempotency_key(instance_id: UUID, step_name: str, attempt: int) -> str:
    """Ключ идемпотентности шага.

    Детерминированная функция от (инстанс, шаг, попытка): одинаковые
    входы дают одинаковый ключ, поэтому повторное исполнение того же
    шага той же попытки распознаётся в event log'е (ADR-0394).

    Args:
        instance_id: UUID инстанса workflow'а.
        step_name: Имя шага.
        attempt: Номер попытки.

    Returns:
        hex-хеш ``sha256(instance_id|step_name|attempt)``.

    """
    raw = f"{instance_id}|{step_name}|{attempt}".encode()
    return hashlib.sha256(raw).hexdigest()


def _coerce_seconds(raw: Any) -> float | None:
    """Привести значение к положительному числу секунд.

    Args:
        raw: Значение из payload'а инстанса (``None`` / str / float).

    Returns:
        Число секунд либо ``None``, если значение не задано или неположительно.

    """
    if raw is None:
        return None
    try:
        value = float(raw)
    except TypeError, ValueError:
        return None
    return value if value > 0 else None


# -- Типы для step-executor контракта ----------------------------------


class StepOutcome:
    """Дискретные исходы выполнения one step."""

    CONTINUE = "continue"  # next step — сразу
    PAUSE = "pause"  # wait + schedule next_attempt_at
    SUB_SPAWNED = "sub_spawned"  # запущен child, ждём его completion
    DONE = "done"  # workflow finished success
    FAILED = "failed"  # terminal failure (после всех retry)


@dataclass(slots=True, frozen=True)
class StepResult:
    """Исход выполнения одного step, возвращаемый step executor-ом.

    Поля:
      * ``outcome`` — одно из ``StepOutcome.*``.
      * ``events`` — events для append в event_log (step_started /
        step_finished / step_failed / branch_taken / loop_iter /
        sub_spawned и т. д.). Runner сам не добавляет events — полный
        контроль за executor.
      * ``next_attempt_at`` — для ``PAUSE`` / ``FAILED`` (retry later).
      * ``output_state`` — materialized state после step (для snapshot).
      * ``error_message`` — при ``FAILED``.
      * ``attempts`` — номер текущей попытки (для retry-бюджета).
      * ``max_attempts`` — retry-бюджет из спецификации (``None`` —
        используется :attr:`RunnerConfig.max_attempts_default`).
    """

    outcome: str
    events: list[tuple[WorkflowEventType, dict[str, Any], str | None]] = field(
        default_factory=list
    )
    next_attempt_at: datetime | None = None
    output_state: dict[str, Any] | None = None
    error_message: str | None = None
    attempts: int | None = None
    max_attempts: int | None = None


class StepExecutor(Protocol):
    """Контракт step-executor-а (IL-WF1.3 реализует DSL-based executor).

    Принимает: instance + materialized state + spec (callable returning
    Pipeline из RouteRegistry — hot-reload).

    Возвращает: StepResult с events для append.
    """

    async def execute_next(
        self, *, instance: WorkflowInstanceRow, state: WorkflowState
    ) -> StepResult:
        """Execute the next step in a workflow instance.

        Args:
            instance: Current workflow instance row.
            state: Current workflow state.

        Returns:
            StepResult with events to append.

        """
        ...


def _emit_step_metrics(
    *,
    instance: WorkflowInstanceRow,
    step_name: str | None,
    attempt: int | None,
    duration_ms: float,
    result: StepResult,
) -> None:
    """Эмитить workflow-метрики pg-runner'а (ADR-0399).

    Метрики: ``workflow.step_duration`` (длительность шага),
    ``workflow.step_retries`` (число ретраев) и
    ``workflow.compensation_total`` (компенсации из события ``compensated``).

    Args:
        instance: Row workflow-инстанса.
        step_name: Имя выполненного шага (``None`` — шаг неизвестен).
        attempt: Номер попытки шага (``None`` — неизвестен).
        duration_ms: Длительность выполнения шага в миллисекундах.
        result: Исход шага от executor'а.

    """
    workflow_name = instance.workflow_name
    effective_step = step_name or "unknown"
    record_workflow_step_duration(
        workflow_name=workflow_name,
        step_name=effective_step,
        duration_ms=duration_ms,
        outcome=result.outcome,
    )
    record_workflow_step_retries(
        workflow_name=workflow_name,
        step_name=effective_step,
        retries=max(0, (attempt or 1) - 1),
    )
    for event_type, payload, _event_step in result.events:
        if event_type != WorkflowEventType.compensated:
            continue
        steps = payload.get("steps") or []
        record_workflow_compensation(
            workflow_name=workflow_name,
            status=str(payload.get("status") or "unknown"),
            steps=len(steps),
        )


# -- Конфиг + Runner ----------------------------------------------------


@dataclass(slots=True)
class RunnerConfig:
    """Параметры, управляющие жизненным циклом runner-а."""

    worker_id: str = field(
        default_factory=lambda: os.environ.get(
            "WORKFLOW_WORKER_ID", f"worker-{uuid.uuid4().hex[:8]}"
        )
    )
    #: Размер concurrent execution (семантика "up to N parallel instances").
    max_concurrent: int = 8
    #: Лимит для list_pending за один poll.
    batch_size: int = 50
    #: Backup polling interval (жёсткий safety net).
    backup_poll_interval_s: float = 30.0
    #: TTL для advisory lock + DB lease.
    lock_ttl_s: int = 120
    #: Exponential backoff параметры при step_failed retry.
    retry_base_delay_s: float = 60.0
    retry_max_delay_s: float = 3600.0
    retry_multiplier: float = 2.0
    retry_jitter: float = 0.2  # ±20%
    #: Max attempts до compensate + failed.
    max_attempts_default: int = 10
    #: Размер страницы при чтении event log'а. Чтение идёт с пагинацией
    #: по ``after_seq`` до конца — иначе workflow с >1000 событий
    #: откатывается к старому snapshot'у и переисполняет шаги (ADR-0398).
    event_page_size: int = 1000


class DurableWorkflowRunner:
    """Основной background-runner.

    Использование::

        runner = DurableWorkflowRunner(
            config=RunnerConfig(max_concurrent=4),
            executor=dsl_step_executor,
            state_store=WorkflowInstanceStore(),
            event_store=WorkflowEventStore(),
        )
        await runner.start()
        ...
        await runner.stop()

    ADR-0408: исчерпавший попытки шаг публикуется в messaging-DLQ
    (``dlq_writer``). Writer можно задать конструктором или позже —
    :meth:`set_dlq_writer` (DI-мост, как у ``CDCClient``).
    """

    def __init__(
        self,
        *,
        config: RunnerConfig,
        executor: StepExecutor,
        state_store: WorkflowInstanceStore | None = None,
        event_store: WorkflowEventStore | None = None,
        listener_dsn: str | None = None,
        dlq_writer: DLQWriter | None = None,
    ) -> None:
        self._config = config
        self._executor = executor
        self._state_store = state_store or WorkflowInstanceStore()
        self._event_store = event_store or WorkflowEventStore()
        self._listener_dsn = listener_dsn
        # ADR-0408: DLQ-поступление для исчерпавших попыток шагов.
        self._dlq = WorkflowDLQPublisher(dlq_writer)
        # Runtime state
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._running = False
        self._backup_task: asyncio.Task[None] | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._pending_instance_ids: asyncio.Queue[UUID] = asyncio.Queue()
        self._active_executions: set[UUID] = set()
        self._active_lock = asyncio.Lock()
        # Cycle-32 (D-AUDIT-3202): shutdown Event для wakeup LISTEN/poll loops
        # без busy-wait (ASYNC110).
        self._shutdown_event: asyncio.Event = asyncio.Event()

    # -- Lifecycle --------------------------------------------------

    async def start(self) -> None:
        """Start the workflow runner with listener, backup poll, and dispatcher."""
        if self._running:
            return
        self._running = True
        # 1) LISTEN worker (если asyncpg доступен и DSN задан).
        if self._listener_dsn is not None:
            self._listen_task = get_task_registry().create_task(
                self._listen_loop(), name="wf-listen"
            )
        # 2) backup polling loop.
        self._backup_task = get_task_registry().create_task(
            self._backup_loop(), name="wf-backup-poll"
        )
        # 3) dispatcher loop — читает из queue и запускает workers.
        get_task_registry().create_task(self._dispatch_loop(), name="wf-dispatch")
        _logger.info(
            "workflow runner started",
            extra={
                "worker_id": self._config.worker_id,
                "max_concurrent": self._config.max_concurrent,
                "listen_enabled": self._listener_dsn is not None,
            },
        )

    async def stop(self) -> None:
        """Stop the workflow runner and wait for active executions to complete."""
        self._running = False
        # Cycle-32 (D-AUDIT-3202): wakeup LISTEN/poll loops via shutdown Event.
        self._shutdown_event.set()
        for task in (self._listen_task, self._backup_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError, Exception:
                    _logger.debug(
                        "workflow runner task cancellation raised", exc_info=True
                    )
        # Ждём завершения активных executions (до lock_ttl_s — иначе drop).
        # Cycle-32 (D-AUDIT-3201): asyncio.Event вместо busy-wait (ASNYC110).
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._config.lock_ttl_s
        # Periodic timer event для wakeup без busy-loop.
        _wakeup = asyncio.Event()
        loop.call_later(0.5, _wakeup.set)
        while self._active_executions and loop.time() < deadline:
            try:
                await asyncio.wait_for(_wakeup.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
            _wakeup.clear()
            _wakeup = asyncio.Event()
            loop.call_later(0.5, _wakeup.set)
        _logger.info("workflow runner stopped")

    # -- Listen loop (push path) ------------------------------------

    async def _listen_loop(self) -> None:
        try:
            import asyncpg
        except ImportError:
            _logger.warning("asyncpg not installed; LISTEN path disabled")
            return

        assert (  # nosec
            self._listener_dsn is not None
        )  # mypy narrowing (проверка осуществлена выше через ImportError-guard)

        # LISTEN/NOTIFY — механизм PostgreSQL. Для других СУБД (SQLite в
        # dev_light) asyncpg не понимает DSN и падает с «invalid DSN» —
        # push-path отключаем, worker работает в backup-polling режиме.
        if not self._listener_dsn.startswith(("postgresql://", "postgres://")):
            _logger.warning(
                "LISTEN path disabled: DSN scheme %r is not PostgreSQL",
                self._listener_dsn.split("://", 1)[0],
            )
            return

        conn = None
        try:
            conn = await asyncpg.connect(self._listener_dsn)
            await conn.add_listener("workflow_pending", self._on_notify)
            _logger.info("listening on channel 'workflow_pending'")
            # Держим соединение открытым; asyncpg sama маршрутизирует
            # уведомления в callback.
            # Cycle-32 (D-AUDIT-3202): asyncio.Event вместо busy-wait (ASYNC110).
            while self._running:
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                if self._shutdown_event.is_set():
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.error("LISTEN loop error: %s", exc)
        finally:
            if conn is not None:
                try:
                    await conn.remove_listener("workflow_pending", self._on_notify)
                finally:
                    await conn.close()

    def _on_notify(
        self, connection: Any, _pid: int, channel: str, payload: str
    ) -> None:
        """Asyncpg callback (sync) — только enqueue."""
        if not payload:
            return
        try:
            workflow_id = UUID(payload)
        except ValueError:
            _logger.warning("invalid notify payload: %s", payload)
            return
        try:
            self._pending_instance_ids.put_nowait(workflow_id)
        except asyncio.QueueFull:
            # Backup polling всё равно подхватит.
            pass

    # -- Backup polling (safety net) --------------------------------

    async def _backup_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._config.backup_poll_interval_s)
                pending = await self._state_store.list_pending(
                    limit=self._config.batch_size
                )
                for row in pending:
                    try:
                        self._pending_instance_ids.put_nowait(row.id)
                    except asyncio.QueueFull:
                        break
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _logger.error("backup poll error: %s", exc)

    # -- Dispatcher loop --------------------------------------------

    async def _dispatch_loop(self) -> None:
        while self._running:
            try:
                workflow_id = await asyncio.wait_for(
                    self._pending_instance_ids.get(), timeout=5.0
                )
            except TimeoutError:
                continue
            async with self._active_lock:
                if workflow_id in self._active_executions:
                    continue
                self._active_executions.add(workflow_id)
            # Fire-and-forget: semaphore ограничивает concurrency.
            get_task_registry().create_task(
                self._execute_one(workflow_id), name=f"wf-exec-{workflow_id}"
            )

    async def _execute_one(self, workflow_id: UUID) -> None:
        async with self._semaphore:
            try:
                await self._run_step(workflow_id)
            except Exception as exc:
                _logger.exception(
                    "unexpected error executing workflow %s: %s", workflow_id, exc
                )
            finally:
                async with self._active_lock:
                    self._active_executions.discard(workflow_id)

    # -- Core: one-step execution -----------------------------------

    async def _run_step(self, workflow_id: UUID) -> None:
        """Lock → replay → execute → record → unlock."""
        # 1) Acquire lock
        locked = await self._state_store.try_lock(
            workflow_id=workflow_id,
            worker_id=self._config.worker_id,
            ttl_s=self._config.lock_ttl_s,
        )
        if not locked:
            _logger.debug("lock busy: %s", workflow_id)
            return

        # Heartbeat продлевает lease: TTL короче таймаута шага, иначе
        # backup-poll подхватит инстанст и выполнит шаг второй раз.
        heartbeat = self._start_heartbeat(workflow_id)
        lease_released = False
        try:
            # 2) Read instance + replay events → WorkflowState.
            instance = await self._state_store.get(workflow_id)
            if instance is None:
                _logger.warning("instance vanished: %s", workflow_id)
                return
            if instance.status in {
                WorkflowStatus.succeeded,
                WorkflowStatus.failed,
                WorkflowStatus.cancelled,
            }:
                return

            # 3) Replay событий → state. Читаем ДО проверки отмены:
            #    отменённый шаг нужно уметь назвать (ADR-0414).
            events = await self._read_all_events(workflow_id)
            state = (
                WorkflowState.replay(events)
                if events
                else WorkflowState(workflow_id=workflow_id)
            )

            # 4) Отмена финализируется ДО execute_next — шаги не идут.
            if instance.status == WorkflowStatus.cancelling:
                await self._finalize_cancelled(
                    workflow_id=workflow_id, instance=instance, state=state
                )
                return

            # 5) Transition to 'running' if needed.
            if instance.status == WorkflowStatus.pending:
                await self._state_store.update_status(
                    workflow_id, WorkflowStatus.running
                )

            # 6) Pre-step событие: пишем ДО выполнения шага, чтобы падение
            #    между эффектом шага и append'ом результата было
            #    распознаваемо (ADR-0394).
            resolved = self._resolve_step(instance, state)
            attempt: int | None = None
            step_key: str | None = None
            pre_step_name: str | None = None
            last_seq = 0
            if resolved is not None:
                pre_step_name, attempt = resolved
                step_key = idempotency_key(instance.id, pre_step_name, attempt)
                started_payload = {
                    "cursor": state.current_step,
                    "attempt": attempt,
                    "idempotency_key": step_key,
                }
                last_seq = await self._event_store.append(
                    workflow_id=workflow_id,
                    event_type=WorkflowEventType.step_started,
                    payload=started_payload,
                    step_name=pre_step_name,
                )
                state.apply_event(
                    WorkflowEventType.step_started, started_payload, pre_step_name
                )
                # ADR-0414: аудит старта шага — один раз на
                # (инстанс, шаг, попытка).
                if not step_start_logged(
                    events, step_name=pre_step_name, attempt=attempt, step_key=step_key
                ):
                    emit_step_audit(
                        phase=PHASE_STARTED,
                        route_id=instance.route_id,
                        step=pre_step_name,
                        tenant_id=instance.tenant_id,
                        attempt=attempt,
                        duration_ms=0.0,
                        workflow_id=str(workflow_id),
                    )

            # 7) Execute next step via injected executor.
            step_started_at = time.perf_counter()
            result: StepResult = await self._executor.execute_next(
                instance=instance, state=state
            )
            step_duration_ms = (time.perf_counter() - step_started_at) * 1000.0
            _emit_step_metrics(
                instance=instance,
                step_name=pre_step_name,
                attempt=attempt,
                duration_ms=step_duration_ms,
                result=result,
            )

            # 8) Append events + синхронизируем in-memory state с event log'ом.
            for event_type, payload, step_name in result.events:
                if (
                    event_type == WorkflowEventType.step_started
                    and step_key is not None
                    and step_name == pre_step_name
                    and int(payload.get("attempt", -1)) == attempt
                ):
                    # Pre-step событие уже записано — дубликат не пишем.
                    continue
                if (
                    event_type == WorkflowEventType.step_finished
                    and step_key is not None
                ):
                    payload = {**payload, "idempotency_key": step_key}
                last_seq = await self._event_store.append(
                    workflow_id=workflow_id,
                    event_type=event_type,
                    payload=payload,
                    step_name=step_name,
                )
                state.apply_event(event_type, payload, step_name)

            # 9) ADR-0414: терминальный исход шага → audit-событие.
            self._emit_step_terminal_audit(
                workflow_id=workflow_id,
                instance=instance,
                result=result,
                pre_step_name=pre_step_name,
                attempt=attempt,
                step_key=step_key,
                duration_ms=step_duration_ms,
                events=events,
            )

            # 10) Persist snapshot — данные между шагами не теряются.
            if result.output_state:
                self._merge_output_state(state, result.output_state)
            # 11) Snapshot в event log: событие ``snapshotted`` + колонка
            #     ``snapshot_state`` (её читает admin-API). Replay стартует
            #     с последнего snapshot'а (ADR-0394).
            await self._event_store.snapshot(
                workflow_id=workflow_id, state=state.to_snapshot(), at_seq=last_seq
            )

            # 12) Handle outcome.
            if result.outcome == StepOutcome.CONTINUE:
                # CONTINUE не меняет статус — освобождаем lease ДО re-enqueue,
                # иначе следующий pickup не захватит lease (ADR-0394).
                await self._stop_heartbeat(heartbeat)
                await self._state_store.unlock(
                    workflow_id=workflow_id, worker_id=self._config.worker_id
                )
                lease_released = True

            await self._apply_outcome(workflow_id, result, state, instance)

        finally:
            await self._stop_heartbeat(heartbeat)
            if not lease_released:
                await self._state_store.unlock(
                    workflow_id=workflow_id, worker_id=self._config.worker_id
                )

    async def _finalize_cancelled(
        self, *, workflow_id: UUID, instance: WorkflowInstanceRow, state: WorkflowState
    ) -> None:
        """Финализировать отмену workflow'а + аудит отменённого шага.

        Отмена финализируется ДО ``execute_next`` — шаги не идут. Шаг,
        который не был выполнен из-за отмены, получает терминальный
        исход ``cancelled`` в audit-событии (ADR-0414). Если шаг
        определить нельзя (спека недоступна / курсор за концом) —
        audit-события нет (нечего аудировать).

        Args:
            workflow_id: UUID workflow-инстанса.
            instance: Row workflow-инстанса.
            state: Materialized state (для определения pending-шага).

        """
        resolved = self._resolve_step(instance, state)
        cancelled_step = resolved[0] if resolved is not None else None
        cancelled_attempt = resolved[1] if resolved is not None else None

        seq = await self._event_store.append(
            workflow_id=workflow_id,
            event_type=WorkflowEventType.cancelled,
            payload={"reason": "cancel_requested"},
            step_name=None,
        )
        await self._state_store.update_status(workflow_id, WorkflowStatus.cancelled)
        record_workflow_status(
            workflow_name=instance.workflow_name, status=WorkflowStatus.cancelled.value
        )
        if cancelled_step:
            emit_step_audit(
                phase=PHASE_CANCELLED,
                route_id=instance.route_id,
                step=cancelled_step,
                tenant_id=instance.tenant_id,
                attempt=cancelled_attempt,
                workflow_id=str(workflow_id),
            )
        await self._write_snapshot(workflow_id, seq)

    def _emit_step_terminal_audit(
        self,
        *,
        workflow_id: UUID,
        instance: WorkflowInstanceRow,
        result: StepResult,
        pre_step_name: str | None,
        attempt: int | None,
        step_key: str | None,
        duration_ms: float,
        events: list[WorkflowEventRow],
    ) -> None:
        """Эмитит audit-событие терминального исхода шага (ADR-0414).

        Терминальный исход шага — последнее из событий
        ``step_finished`` / ``step_failed`` в результате executor'а.
        Повторный запуск шага (переpickup инстанста) событие не
        дублирует: терминальный исход уже зафиксирован в event log'е.

        Args:
            workflow_id: UUID workflow-инстанса.
            instance: Row workflow-инстанса.
            result: Результат шага от executor'а.
            pre_step_name: Имя pre-step (по ``describe_next``) — ``None``,
                если executor работает в legacy-режиме.
            attempt: Номер попытки шага.
            step_key: Ключ идемпотентности шага.
            duration_ms: Длительность выполнения шага в миллисекундах.
            events: События инстанса, прочитанные до текущего запуска.

        """
        phase: str | None = None
        terminal_step: str | None = None
        terminal_attempt: int | None = None
        for event_type, payload, step_name in result.events:
            if event_type == WorkflowEventType.step_finished:
                phase = PHASE_SUCCEEDED
            elif event_type == WorkflowEventType.step_failed:
                phase = PHASE_FAILED
            else:
                continue
            terminal_step = step_name
            raw_attempt = payload.get("attempt")
            terminal_attempt = raw_attempt if isinstance(raw_attempt, int) else attempt
        if phase is None:
            return
        step = pre_step_name or terminal_step
        if not step:
            return
        if step_terminal_logged(
            events, step_name=step, attempt=terminal_attempt, step_key=step_key
        ):
            return
        emit_step_audit(
            phase=phase,
            route_id=instance.route_id,
            step=step,
            tenant_id=instance.tenant_id,
            attempt=terminal_attempt,
            duration_ms=duration_ms,
            workflow_id=str(workflow_id),
        )

    async def _apply_outcome(
        self,
        workflow_id: UUID,
        result: StepResult,
        state: WorkflowState,
        instance: WorkflowInstanceRow,
    ) -> None:
        """Transition status + schedule next attempt per outcome."""
        if result.outcome == StepOutcome.DONE:
            await self._state_store.update_status(workflow_id, WorkflowStatus.succeeded)
            record_workflow_status(
                workflow_name=instance.workflow_name,
                status=WorkflowStatus.succeeded.value,
            )
            self._record_sla_compliance(instance=instance)
            return

        if result.outcome == StepOutcome.FAILED:
            await self._state_store.update_status(
                workflow_id,
                WorkflowStatus.failed,
                error=result.error_message or "unknown",
            )
            record_workflow_status(
                workflow_name=instance.workflow_name, status=WorkflowStatus.failed.value
            )
            await self._publish_exhausted_step(
                instance=instance,
                result=result,
                attempts=result.attempts,
                max_attempts=result.max_attempts,
            )
            self._record_sla_compliance(instance=instance)
            return

        if result.outcome == StepOutcome.SUB_SPAWNED:
            # Остаёмся running; ожидаем sub_completed event от child.
            return

        if result.outcome == StepOutcome.PAUSE:
            attempts = (
                result.attempts if result.attempts is not None else state.attempts
            )
            max_attempts = (
                result.max_attempts
                if result.max_attempts is not None
                else self._config.max_attempts_default
            )
            if attempts >= max_attempts:
                # Retry-бюджет исчерпан → терминальный FAILED (ADR-0394).
                await self._state_store.update_status(
                    workflow_id,
                    WorkflowStatus.failed,
                    error=(
                        f"max_attempts exceeded ({attempts}/{max_attempts}): "
                        f"{result.error_message or 'step failed'}"
                    ),
                )
                record_workflow_status(
                    workflow_name=instance.workflow_name,
                    status=WorkflowStatus.failed.value,
                )
                # ADR-0408: исчерпанный шаг → DLQ.
                await self._publish_exhausted_step(
                    instance=instance,
                    result=result,
                    attempts=attempts,
                    max_attempts=max_attempts,
                )
                self._record_sla_compliance(instance=instance)
                return
            next_at = result.next_attempt_at or (
                datetime.now(UTC)
                + timedelta(seconds=self._compute_backoff(max(0, attempts - 1)))
            )
            await self._state_store.update_status(
                workflow_id, WorkflowStatus.paused, next_attempt_at=next_at
            )
            record_workflow_status(
                workflow_name=instance.workflow_name, status=WorkflowStatus.paused.value
            )
            return

        if result.outcome == StepOutcome.CONTINUE:
            # id убираем из active ДО re-enqueue: иначе _dispatch_loop
            # отбросит элемент очереди как дубликат активной execution'и
            # и следующий шаг ждал бы backup-poll (ADR-0394).
            async with self._active_lock:
                self._active_executions.discard(workflow_id)
            try:
                self._pending_instance_ids.put_nowait(workflow_id)
            except asyncio.QueueFull:
                pass
            return

        _logger.warning(
            "unknown outcome %r for %s; treating as pause", result.outcome, workflow_id
        )
        next_at = datetime.now(UTC) + timedelta(
            seconds=self._compute_backoff(state.attempts)
        )
        await self._state_store.update_status(
            workflow_id, WorkflowStatus.paused, next_attempt_at=next_at
        )

    # -- DLQ + SLA (ADR-0408) -------------------------------------------

    def set_dlq_writer(self, writer: DLQWriter | None) -> None:
        """Установить DLQ-writer для исчерпанных шагов (DI-мост).

        Args:
            writer: Canonical ``DLQWriter`` (например ``InboxDLQWriter``).
                ``None`` — публикация отключается (fail-loud warning-лог).

        """
        self._dlq = WorkflowDLQPublisher(writer)

    def _resolve_dlq_writer(self) -> DLQWriter | None:
        """Определить writer DLQ: инъекция → fallback на PG ``dlq_inbox``.

        Fallback нужен, чтобы контракт работал без правок composition root
        (вне зоны кластера): pg-runner и DLQ живут в одной PostgreSQL —
        таблица ``dlq_inbox`` (тот же writer, что у outbox-DLQ). Ошибка
        построения writer'а workflow не ломает: запись помечается
        статусом ``no_writer`` (alert-рул, ADR-0408).

        Returns:
            Writer либо ``None`` — writer недоступен.

        """
        writer = self._dlq.writer
        if writer is not None:
            return writer
        try:
            from src.backend.infrastructure.database.session_manager import (
                main_session_manager,
            )
            from src.backend.infrastructure.messaging.dlq.inbox_writer import (
                InboxDLQWriter,
            )

            writer = InboxDLQWriter(session_factory=main_session_manager.create_session)
        except Exception as exc:
            _logger.warning("workflow.dlq.default_writer_unavailable: %s", exc)
            return None
        self.set_dlq_writer(writer)
        return writer

    async def _publish_exhausted_step(
        self,
        *,
        instance: WorkflowInstanceRow,
        result: StepResult,
        attempts: int | None,
        max_attempts: int | None,
    ) -> None:
        """Опубликовать исчерпанный шаг в messaging-DLQ (ADR-0408).

        В DLQ попадает только шаг, исчерпавший retry-бюджет
        (``attempts >= max_attempts``); прочие терминальные сбои — нет.
        ``dlq_id`` детерминирован (ключ идемпотентности шага), поэтому
        повторный запуск того же шага не дублирует запись.

        Args:
            instance: Row workflow-инстанса.
            result: Результат шага (источник имени шага и текста ошибки).
            attempts: Номер последней попытки (``None`` — неизвестен).
            max_attempts: Размер retry-бюджета (``None`` — неизвестен).

        """
        if attempts is None or max_attempts is None or attempts < max_attempts:
            return
        self._resolve_dlq_writer()
        step_name = self._failed_step_name(result)
        payload = instance.input_payload or {}
        await self._dlq.publish_exhausted_step(
            dlq_id=idempotency_key(instance.id, step_name, attempts),
            instance=instance,
            step_name=step_name,
            attempts=attempts,
            max_attempts=max_attempts,
            error_message=result.error_message,
            payload_keys=[key for key in payload if not str(key).startswith("__")],
        )

    @staticmethod
    def _failed_step_name(result: StepResult) -> str:
        """Имя шага, породившего результат (по событию ``step_failed``)."""
        for event_type, _payload, step_name in reversed(result.events):
            if event_type == WorkflowEventType.step_failed and step_name:
                return str(step_name)
        return "unknown"

    def _record_sla_compliance(self, *, instance: WorkflowInstanceRow) -> None:
        """Оценить SLA инстанса → ``workflow_sla_compliance_total`` (ADR-0408).

        Бюджет времени workflow'а — маркер ``__sla_hard_limit_s`` либо
        ``__execution_timeout_s`` (ADR-0396: ``execution_timeout`` = SLA
        hard-limit), либо ``run_timeout_s`` спеки workflow'а. Без бюджета
        SLA не оценивается (метрика не растёт).

        Args:
            instance: Row workflow-инстанса.

        """
        hard = self._sla_budget_seconds(instance=instance)
        if hard is None:
            return
        payload = instance.input_payload or {}
        created = instance.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        elapsed = (datetime.now(UTC) - created).total_seconds()
        record_workflow_sla_compliance(
            classify_sla_breach(
                elapsed_seconds=elapsed,
                soft_limit_seconds=_coerce_seconds(payload.get("__sla_soft_limit_s")),
                hard_limit_seconds=hard,
            )
        )

    @staticmethod
    def _sla_budget_seconds(*, instance: WorkflowInstanceRow) -> float | None:
        """Бюджет времени workflow'а (SLA hard-limit) в секундах.

        Приоритет источников: маркеры payload'а инстанса
        (``__sla_hard_limit_s`` → ``__execution_timeout_s``, ADR-0396) →
        ``run_timeout_s`` спеки workflow'а из реестра workflow'ов.

        Args:
            instance: Row workflow-инстанса.

        Returns:
            Бюджет в секундах либо ``None`` — бюджет не задан.

        """
        payload = instance.input_payload or {}
        budget = _coerce_seconds(payload.get("__sla_hard_limit_s"))
        if budget is None:
            budget = _coerce_seconds(payload.get("__execution_timeout_s"))
        if budget is None:
            spec = workflow_registry.get_spec(instance.route_id)
            budget = _coerce_seconds(getattr(spec, "run_timeout_s", None))
        return budget

    # -- Lease heartbeat ------------------------------------------------

    def _start_heartbeat(
        self, workflow_id: UUID
    ) -> tuple[asyncio.Task[None], asyncio.Event] | None:
        """Стартует фоновую задачу продления lease инстанса.

        Returns:
            Пара ``(task, stop_event)`` либо ``None``, если реестр задач
            закрыт (shutdown).

        """
        stop = asyncio.Event()
        try:
            task = get_task_registry().create_task(
                self._lease_heartbeat(workflow_id, stop), name=f"wf-lease-{workflow_id}"
            )
        except RuntimeError as exc:
            # Реестр закрыт (shutdown) — работаем без heartbeat.
            _logger.warning("lease heartbeat not started: %s", exc)
            return None
        return task, stop

    @staticmethod
    async def _stop_heartbeat(
        heartbeat: tuple[asyncio.Task[None], asyncio.Event] | None,
    ) -> None:
        """Останавливает heartbeat-задачу (если она была запущена)."""
        if heartbeat is None:
            return
        task, stop = heartbeat
        stop.set()
        if task.done():
            return
        try:
            await task
        except asyncio.CancelledError:
            # Отмена самого heartbeat'а — штатная ситуация; отмена
            # вызывающей задачи пробрасывается дальше.
            if not task.cancelled():
                raise
        except Exception:
            _logger.debug("lease heartbeat stopped", exc_info=True)

    async def _lease_heartbeat(self, workflow_id: UUID, stop: asyncio.Event) -> None:
        """Продлевает lease, пока выполняется шаг.

        TTL lease (по умолчанию 120 с) короче дефолтного таймаута шага
        (300 с) — без продления backup-poll подхватил бы инстанст и
        выполнил шаг повторно (ADR-0394).
        """
        interval = max(0.1, self._config.lock_ttl_s / 3)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                pass
            else:
                return
            if stop.is_set():
                return
            try:
                renewed = await self._state_store.renew_lock(
                    workflow_id=workflow_id,
                    worker_id=self._config.worker_id,
                    ttl_s=self._config.lock_ttl_s,
                )
            except Exception as exc:
                _logger.warning("lease renewal error for %s: %s", workflow_id, exc)
                continue
            if not renewed:
                _logger.warning(
                    "lease lost for %s — another worker took over", workflow_id
                )
                return

    # -- Helpers ----------------------------------------------------

    def _resolve_step(
        self, instance: WorkflowInstanceRow, state: WorkflowState
    ) -> tuple[str, int] | None:
        """Определяет имя шага и номер попытки для pre-step события.

        Executor может описать следующий шаг (``describe_next``) — тогда
        pre-step событие пишется до эффекта шага. Executor'ы без такого
        метода работают в прежнем режиме (событие пишет сам executor).

        Args:
            instance: Row инстанса workflow'а.
            state: Materialized state.

        Returns:
            Пара ``(step_name, attempt)`` либо ``None``.

        """
        describe = getattr(self._executor, "describe_next", None)
        if describe is None:
            return None
        descriptor = describe(instance=instance, state=state)
        if descriptor is None:
            return None
        return str(descriptor.name), int(descriptor.attempt)

    async def _write_snapshot(self, workflow_id: UUID, at_seq: int) -> None:
        """Фиксирует snapshot состояния инстанса (событие ``snapshotted``)."""
        events = await self._read_all_events(workflow_id)
        if not events:
            return
        state = WorkflowState.replay(events)
        await self._event_store.snapshot(
            workflow_id=workflow_id, state=state.to_snapshot(), at_seq=at_seq
        )

    async def _read_all_events(self, workflow_id: UUID) -> list[WorkflowEventRow]:
        """Читает ВСЕ события workflow'а — с пагинацией по ``after_seq``.

        Event log' растёт линейно по числу шагов (и по числу сигналов/
        ретраев), поэтому одностраничное чтение обрезало бы лог на
        ``event_page_size`` событиях. Replay тогда не нашёл бы последний
        ``snapshotted``, состояние откатывалось к старому snapshot'у, а
        уже выполненные шаги исполнялись повторно (ADR-0398).

        Args:
            workflow_id: UUID workflow-инстанса.

        Returns:
            Список всех событий в порядке возрастания ``seq``.

        """
        page_size = max(1, self._config.event_page_size)
        events: list[WorkflowEventRow] = []
        after_seq = 0
        while True:
            page = await self._event_store.read_events(
                workflow_id=workflow_id, after_seq=after_seq, limit=page_size
            )
            if not page:
                break
            events.extend(page)
            last_seq = page[-1].seq
            if last_seq <= after_seq:
                # Store не продвинул курсор — дальнейшее чтение
                # зациклится. Защита от бесконечного цикла.
                break
            after_seq = last_seq
            if len(page) < page_size:
                break
        return events

    @staticmethod
    def _merge_output_state(state: WorkflowState, output_state: dict[str, Any]) -> None:
        """Применяет ``StepResult.output_state`` к материализованному state."""
        exchange = output_state.get("exchange_snapshot")
        if isinstance(exchange, dict):
            state.exchange_snapshot = dict(exchange)
        loop_counters = output_state.get("loop_counters")
        if isinstance(loop_counters, dict):
            state.loop_counters.update(
                {str(k): v for k, v in loop_counters.items() if isinstance(v, int)}
            )
        wait_deadlines = output_state.get("wait_deadlines")
        if isinstance(wait_deadlines, dict):
            state.wait_deadlines.update(
                {str(k): str(v) for k, v in wait_deadlines.items()}
            )

    def _compute_backoff(self, attempt: int) -> float:
        """Exponential backoff с jitter.

        delay = min(max_delay, base * multiplier ** attempt) * (1 ± jitter)
        """
        base = self._config.retry_base_delay_s
        mult = self._config.retry_multiplier
        max_delay = self._config.retry_max_delay_s
        raw = min(max_delay, base * (mult ** max(0, attempt)))
        jitter = self._config.retry_jitter
        return raw * (
            1
            + random.uniform(
                -jitter, jitter
            )  # non-cryptographic use  # nosec B311 — non-crypto use
        )  # retry-jitter, не криптография
