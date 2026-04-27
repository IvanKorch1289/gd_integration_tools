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
import logging
import os
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID

from src.infrastructure.database.models.workflow_event import WorkflowEventType
from src.infrastructure.database.models.workflow_instance import WorkflowStatus
from src.infrastructure.workflow.event_store import WorkflowEventStore
from src.infrastructure.workflow.state import WorkflowState
from src.infrastructure.workflow.state_store import (
    WorkflowInstanceRow,
    WorkflowInstanceStore,
)

__all__ = ("DurableWorkflowRunner", "StepExecutor", "StepResult", "RunnerConfig")


_logger = logging.getLogger("workflow.runner")


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
    """

    outcome: str
    events: list[tuple[WorkflowEventType, dict[str, Any], str | None]] = field(
        default_factory=list
    )
    next_attempt_at: datetime | None = None
    output_state: dict[str, Any] | None = None
    error_message: str | None = None


class StepExecutor(Protocol):
    """Контракт step-executor-а (IL-WF1.3 реализует DSL-based executor).

    Принимает: instance + materialized state + spec (callable returning
    Pipeline из RouteRegistry — hot-reload).

    Возвращает: StepResult с events для append.
    """

    async def execute_next(
        self, *, instance: WorkflowInstanceRow, state: WorkflowState
    ) -> StepResult: ...


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
    """

    def __init__(
        self,
        *,
        config: RunnerConfig,
        executor: StepExecutor,
        state_store: WorkflowInstanceStore | None = None,
        event_store: WorkflowEventStore | None = None,
        listener_dsn: str | None = None,
    ) -> None:
        self._config = config
        self._executor = executor
        self._state_store = state_store or WorkflowInstanceStore()
        self._event_store = event_store or WorkflowEventStore()
        self._listener_dsn = listener_dsn
        # Runtime state
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._running = False
        self._backup_task: asyncio.Task[None] | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._pending_instance_ids: asyncio.Queue[UUID] = asyncio.Queue()
        self._active_executions: set[UUID] = set()
        self._active_lock = asyncio.Lock()

    # -- Lifecycle --------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # 1) LISTEN worker (если asyncpg доступен и DSN задан).
        if self._listener_dsn is not None:
            self._listen_task = asyncio.create_task(
                self._listen_loop(), name="wf-listen"
            )
        # 2) backup polling loop.
        self._backup_task = asyncio.create_task(
            self._backup_loop(), name="wf-backup-poll"
        )
        # 3) dispatcher loop — читает из queue и запускает workers.
        asyncio.create_task(self._dispatch_loop(), name="wf-dispatch")
        _logger.info(
            "workflow runner started",
            extra={
                "worker_id": self._config.worker_id,
                "max_concurrent": self._config.max_concurrent,
                "listen_enabled": self._listener_dsn is not None,
            },
        )

    async def stop(self) -> None:
        self._running = False
        for task in (self._listen_task, self._backup_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError, Exception:  # noqa: BLE001
                    pass
        # Ждём завершения активных executions (до lock_ttl_s — иначе drop).
        deadline = asyncio.get_event_loop().time() + self._config.lock_ttl_s
        while self._active_executions and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.5)
        _logger.info("workflow runner stopped")

    # -- Listen loop (push path) ------------------------------------

    async def _listen_loop(self) -> None:
        try:
            import asyncpg
        except ImportError:
            _logger.warning("asyncpg not installed; LISTEN path disabled")
            return

        assert self._listener_dsn is not None
        conn = None
        try:
            conn = await asyncpg.connect(self._listener_dsn)
            await conn.add_listener("workflow_pending", self._on_notify)
            _logger.info("listening on channel 'workflow_pending'")
            # Держим соединение открытым; asyncpg sama маршрутизирует
            # уведомления в callback.
            while self._running:
                await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            _logger.error("LISTEN loop error: %s", exc)
        finally:
            if conn is not None:
                try:
                    await conn.remove_listener("workflow_pending", self._on_notify)
                finally:
                    await conn.close()

    def _on_notify(self, connection: Any, pid: int, channel: str, payload: str) -> None:
        """asyncpg callback (sync) — только enqueue."""
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
            except Exception as exc:  # noqa: BLE001
                _logger.error("backup poll error: %s", exc)

    # -- Dispatcher loop --------------------------------------------

    async def _dispatch_loop(self) -> None:
        while self._running:
            try:
                workflow_id = await asyncio.wait_for(
                    self._pending_instance_ids.get(), timeout=5.0
                )
            except asyncio.TimeoutError:
                continue
            async with self._active_lock:
                if workflow_id in self._active_executions:
                    continue
                self._active_executions.add(workflow_id)
            # Fire-and-forget: semaphore ограничивает concurrency.
            asyncio.create_task(
                self._execute_one(workflow_id), name=f"wf-exec-{workflow_id}"
            )

    async def _execute_one(self, workflow_id: UUID) -> None:
        async with self._semaphore:
            try:
                await self._run_step(workflow_id)
            except Exception as exc:  # noqa: BLE001
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

            events = await self._event_store.read_events(workflow_id=workflow_id)
            state = WorkflowState.replay(events)

            # 3) Transition to 'running' if needed.
            if instance.status == WorkflowStatus.pending:
                await self._state_store.update_status(
                    workflow_id, WorkflowStatus.running
                )

            # 4) Execute next step via injected executor.
            result: StepResult = await self._executor.execute_next(
                instance=instance, state=state
            )

            # 5) Append events.
            for event_type, payload, step_name in result.events:
                await self._event_store.append(
                    workflow_id=workflow_id,
                    event_type=event_type,
                    payload=payload,
                    step_name=step_name,
                )

            # 6) Handle outcome.
            await self._apply_outcome(workflow_id, result, state, instance)

        finally:
            await self._state_store.unlock(
                workflow_id=workflow_id, worker_id=self._config.worker_id
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
            return

        if result.outcome == StepOutcome.FAILED:
            await self._state_store.update_status(
                workflow_id,
                WorkflowStatus.failed,
                error=result.error_message or "unknown",
            )
            return

        if result.outcome == StepOutcome.SUB_SPAWNED:
            # Остаёмся running; ожидаем sub_completed event от child.
            return

        if result.outcome == StepOutcome.PAUSE:
            next_at = result.next_attempt_at or (
                datetime.now(timezone.utc)
                + timedelta(seconds=self._compute_backoff(state.attempts))
            )
            await self._state_store.update_status(
                workflow_id, WorkflowStatus.paused, next_attempt_at=next_at
            )
            return

        if result.outcome == StepOutcome.CONTINUE:
            # Сразу переставим в очередь для следующего step.
            try:
                self._pending_instance_ids.put_nowait(workflow_id)
            except asyncio.QueueFull:
                pass
            return

        _logger.warning(
            "unknown outcome %r for %s; treating as pause", result.outcome, workflow_id
        )
        next_at = datetime.now(timezone.utc) + timedelta(
            seconds=self._compute_backoff(state.attempts)
        )
        await self._state_store.update_status(
            workflow_id, WorkflowStatus.paused, next_attempt_at=next_at
        )

    # -- Helpers ----------------------------------------------------

    def _compute_backoff(self, attempt: int) -> float:
        """Exponential backoff с jitter.

        delay = min(max_delay, base * multiplier ** attempt) * (1 ± jitter)
        """
        base = self._config.retry_base_delay_s
        mult = self._config.retry_multiplier
        max_delay = self._config.retry_max_delay_s
        raw = min(max_delay, base * (mult ** max(0, attempt)))
        jitter = self._config.retry_jitter
        return raw * (1 + random.uniform(-jitter, jitter))
