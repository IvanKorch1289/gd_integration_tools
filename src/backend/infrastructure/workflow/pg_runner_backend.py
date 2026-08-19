"""`PgRunnerWorkflowBackend` — адаптер ADR-031 pg-runner на Protocol.

.. warning::
    **Non-production-grade fallback.** Этот backend НЕ детектирует
    non-determinism при replay (метод ``replay()`` — no-op).
    Для production используйте ``TemporalWorkflowBackend`` (Wave D.2).
    ``PgRunnerWorkflowBackend`` подходит только для dev/staging/CI.

Wave D.1 / ADR-045 §«PgRunnerWorkflowBackend (legacy fallback)».
Тонкая обёртка над существующими ``WorkflowInstanceStore`` /
``WorkflowEventStore`` + ``DurableWorkflowRunner``: даёт ядру
``WorkflowBackend`` Protocol-фасад без переноса бизнес-логики.

Сравнение семантики с Temporal:

* ``signal_workflow`` → ``INSERT workflow_events(signal_received)``;
  pg_notify-trigger ``trg_workflow_notify`` пробрасывается воркеру.
* ``query_workflow`` → snapshot read из ``workflow_instances.snapshot_state``
  (degraded vs Temporal — не видит in-flight activity).
* ``cancel_workflow`` → ``update_status(cancelling)``; runner подхватывает
  и завершает через event ``cancelled``.
* ``await_completion`` → polling ``state_store.get`` с экспоненциальным
  backoff'ом (нет push-нотификации completion).
* ``replay`` → ``read_events`` с начала; deg-mode (нет detection
  недетерминизма, как в Temporal).

Используется как dev/staging fallback до Wave D.2 (TemporalWorkflowBackend).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from uuid import UUID

from src.backend.core.domain.models.workflow_event import WorkflowEventType
from src.backend.core.domain.models.workflow_instance import WorkflowStatus
from src.backend.core.workflow.backend import (
    WorkflowBackend,
    WorkflowHandle,
    WorkflowResult,
)
from src.backend.infrastructure.workflow.pg_runner_internals import (
    WorkflowEventStore,
    WorkflowInstanceRow,
    WorkflowInstanceStore,
)

__all__ = ("PgRunnerWorkflowBackend",)


_TERMINAL_STATUSES = frozenset(
    (WorkflowStatus.succeeded, WorkflowStatus.failed, WorkflowStatus.cancelled)
)


def _status_to_protocol(status: WorkflowStatus) -> str:
    """Маппинг pg-runner status → ``WorkflowResult.status``."""
    match status:
        case WorkflowStatus.succeeded:
            return "completed"
        case WorkflowStatus.failed:
            return "failed"
        case WorkflowStatus.cancelled:
            return "cancelled"
        case _:  # pragma: no cover — guarded в await_completion
            return status.value


class PgRunnerWorkflowBackend(WorkflowBackend):
    """``WorkflowBackend`` поверх ADR-031 pg-runner stack.

    .. deprecated::
        DEPRECATED since Sprint 217 (2026-08-17) — pg-runner backend
        не реализует Temporal-совместимый replay API и не детектирует
        non-determinism (Phase 0 verification, MULTI_SPRINT_2026-08-17.md).

        Production callers → :class:`TemporalWorkflowBackend`.
        Dev/test/CI может продолжать использовать этот backend,
        но :meth:`replay` всегда raise ``NotImplementedError``.

        Removal: Sprint 220+ (после полной миграции callers).
    """

    def __init__(
        self,
        *,
        state_store: WorkflowInstanceStore | None = None,
        event_store: WorkflowEventStore | None = None,
        poll_interval_s: float = 1.0,
        poll_max_interval_s: float = 5.0,
    ) -> None:
        """Параметры:

        :param state_store: store для ``workflow_instances`` (DI override
            в тестах); по умолчанию singleton из ``state_store.py``.
        :param event_store: append-only store для ``workflow_events``;
            по умолчанию singleton.
        :param poll_interval_s: стартовая пауза polling в
            ``await_completion``.
        :param poll_max_interval_s: верхняя граница экспоненциального
            backoff'а polling'а.
        """
        self._state_store = state_store or WorkflowInstanceStore()
        self._event_store = event_store or WorkflowEventStore()
        self._poll_interval_s = poll_interval_s
        self._poll_max_interval_s = poll_max_interval_s

    async def start_workflow(
        self,
        *,
        workflow_name: str,
        workflow_id: str,
        input: dict[str, Any],
        namespace: str,
        task_queue: str,
        execution_timeout: timedelta | None = None,
    ) -> WorkflowHandle:
        """Создать инстанс через ``state_store.create``.

        ``workflow_id`` (Temporal-style deduplication-tag) хранится в
        ``input_payload["__workflow_id"]`` — pg-runner не использует
        его как unique-key, но adapter возвращает в ``handle``.
        ``run_id`` = hex от UUID нового инстанса. ``namespace`` →
        ``tenant_id`` ("global" → "default" для backward-compat).
        ``task_queue`` хранится в payload для трассировки (pg-runner
        не маршрутизирует по task_queue).
        ``execution_timeout`` сейчас игнорируется (pg-runner управляет
        retry/lease через RunnerConfig); сохраняется в payload.
        """
        tenant_id = "default" if namespace == "global" else namespace
        payload = {
            "__workflow_id": workflow_id,
            "__task_queue": task_queue,
            "__execution_timeout_s": (
                execution_timeout.total_seconds() if execution_timeout else None
            ),
            **input,
        }
        instance_id = await self._state_store.create(
            workflow_name=workflow_name,
            route_id=workflow_name,  # 1:1 — Wave D.2 уточнит mapping через WorkflowRegistry
            input_payload=payload,
            tenant_id=tenant_id,
        )
        return WorkflowHandle(
            workflow_id=workflow_id, run_id=instance_id.hex, namespace=namespace
        )

    async def signal_workflow(
        self, *, handle: WorkflowHandle, signal_name: str, payload: dict[str, Any]
    ) -> None:
        """Append ``signal_received`` event + pg_notify через trigger."""
        instance_id = self._uuid_from_handle(handle)
        await self._event_store.append(
            workflow_id=instance_id,
            event_type=WorkflowEventType.signal_received,
            payload={"signal_name": signal_name, "data": dict(payload)},
            step_name=None,
        )

    async def query_workflow(
        self,
        *,
        handle: WorkflowHandle,
        query_name: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Read snapshot_state[query_name] из header-таблицы.

        deg vs Temporal: нет typed-query handler'ов; возвращается
        срез ``snapshot_state[query_name]`` или весь snapshot при
        ``query_name == "$state"``. Если snapshot пуст — ``{}``.
        """
        instance_id = self._uuid_from_handle(handle)
        row = await self._state_store.get(instance_id)
        if row is None:
            raise KeyError(f"unknown workflow instance run_id={handle.run_id!r}")
        snapshot = dict(row.snapshot_state or {})
        if query_name == "$state":
            return snapshot
        value = snapshot.get(query_name)
        return value if isinstance(value, dict) else {"value": value}

    async def cancel_workflow(self, *, handle: WorkflowHandle) -> None:
        """Перевести инстанс в ``cancelling`` (runner финализирует)."""
        instance_id = self._uuid_from_handle(handle)
        await self._state_store.update_status(instance_id, WorkflowStatus.cancelling)

    async def await_completion(
        self, *, handle: WorkflowHandle, timeout: timedelta | None = None
    ) -> WorkflowResult:
        """Polling ``state_store.get`` до terminal-статуса или timeout.

        Backoff: ``poll_interval_s`` → удваивается до
        ``poll_max_interval_s``. При истечении timeout возвращается
        ``status="timed_out"`` с failure-payload и текущим snapshot.
        """
        instance_id = self._uuid_from_handle(handle)
        deadline: float | None = None
        if timeout is not None:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout.total_seconds()

        interval = self._poll_interval_s
        while True:
            row = await self._state_store.get(instance_id)
            if row is None:
                raise KeyError(f"unknown workflow instance run_id={handle.run_id!r}")
            if row.status in _TERMINAL_STATUSES:
                return self._row_to_result(row)
            if deadline is not None:
                loop = asyncio.get_running_loop()
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return WorkflowResult(
                        output=dict(row.snapshot_state or {}),
                        status="timed_out",
                        failure={
                            "type": "TimeoutError",
                            "message": f"workflow not terminal after timeout, "
                            f"current_status={row.status.value}",
                        },
                    )
                await asyncio.sleep(min(interval, remaining))
            else:
                await asyncio.sleep(interval)
            interval = min(interval * 2, self._poll_max_interval_s)

    async def replay(self, *, workflow_name: str, history: bytes) -> None:
        """pg-runner не реализует Temporal-совместимый replay-gate.

        В отличие от :class:`TemporalWorkflowBackend`, pg-runner работает
        через ``DurableWorkflowRunner.read_events`` (event-sourcing из
        ``workflow_events`` table) — у него нет ``WorkflowHistory.from_json``
        и он не может воспроизводить Temporal history bytes.

        .. deprecated::
            DEPRECATED since Sprint 217 (2026-08-17). pg-runner backend
            deprecated entirely — production callers must migrate to
            :class:`TemporalWorkflowBackend`. This method will be removed
            in Sprint 220+.

        Raises:
            NotImplementedError: всегда (pg-runner не реализует replay API).

        """
        raise NotImplementedError(
            "PgRunnerWorkflowBackend.replay() is DEPRECATED since Sprint 217 "
            "(2026-08-17) — pg-runner backend does not implement Temporal-"
            "compatible replay. Migrate to TemporalWorkflowBackend. "
            "See MULTI_SPRINT_2026-08-17.md Sprint 7 for deprecation timeline."
        )

    async def await_external_signal(
        self,
        *,
        handle: WorkflowHandle,
        signal_name: str,
        timeout: timedelta | None = None,
    ) -> dict[str, Any]:
        """Round 5 Sprint 5.2: polling-реализация для pg-runner backend.

        ADR-031 pg-runner не имеет LISTEN/NOTIFY wait-queue (carryover, см.
        ADR-NEW-21). Реализация через polling ``workflow_events`` table:
        ищем последний ``signal_received`` event с ``signal_name==<signal_name>``
        для instance. Polling interval растёт экспоненциально (1s → 5s max).
        При таймауте возвращаем ``{"timed_out": True}`` (semantics совпадает
        с :class:`FakeWorkflowBackend.await_external_signal`).

        Args:
            handle: Дескриптор ожидающего workflow.
            signal_name: Имя сигнала, которого ждём.
            timeout: Максимальное время ожидания (None = бесконечно).

        Returns:
            Payload сигнала (dict). При таймауте: ``{"timed_out": True}``.

        """
        instance_id = self._uuid_from_handle(handle)
        deadline: float | None = None
        if timeout is not None:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout.total_seconds()

        interval = self._poll_interval_s
        seen_event_ids: set[int] = set()
        # Используем read_events (WorkflowEventStore API, не list_for_workflow):
        # читаем все события после последнего consumed seq.
        last_seq = await self._event_store.latest_seq(instance_id)
        after_seq = 0
        while True:
            events = await self._event_store.read_events(
                workflow_id=instance_id, after_seq=after_seq, limit=1000
            )
            for event in events:
                if event.seq in seen_event_ids:
                    continue
                payload = event.payload or {}
                if (
                    event.event_type is WorkflowEventType.signal_received
                    and payload.get("signal_name") == signal_name
                ):
                    return dict(payload.get("data", {}))
                seen_event_ids.add(event.seq)
            after_seq = max(seen_event_ids, default=last_seq)
            if deadline is not None:
                loop = asyncio.get_running_loop()
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return {"timed_out": True}
                await asyncio.sleep(min(interval, remaining))
            else:
                await asyncio.sleep(interval)
            interval = min(interval * 2, self._poll_max_interval_s)

    async def start_child_workflow(
        self,
        *,
        parent_handle: WorkflowHandle,
        workflow_name: str,
        workflow_id: str,
        input: dict[str, Any],
        task_queue: str,
        execution_timeout: timedelta | None = None,
    ) -> WorkflowHandle:
        """Round 5 Sprint 5.2: запуск child workflow для pg-runner.

        Pg-runner не имеет parent-child cascade через Temporal API.
        Используем тот же ``state_store.create`` path, но помечаем
        ``parent_run_id`` в ``input_payload["__parent_run_id"]`` для
        observability и тестов cancellation cascade. Namespace
        наследуется от parent (multi-tenant consistency).

        Args:
            parent_handle: Дескриптор parent workflow (для namespace inheritance).
            workflow_name: Имя запускаемого workflow.
            workflow_id: Temporal-style deduplication-tag.
            input: Input payload (включая ``__parent_run_id`` маркер).
            task_queue: Task queue (pg-runner игнорирует, хранится для trace).
            execution_timeout: Сохраняется в payload (pg-runner управляет
                retry/lease через RunnerConfig).

        Returns:
            :class:`WorkflowHandle` нового child instance.

        """
        tenant_id = (
            "default"
            if parent_handle.namespace == "global"
            else parent_handle.namespace
        )
        payload = {
            "__workflow_id": workflow_id,
            "__task_queue": task_queue,
            "__parent_run_id": parent_handle.run_id,
            "__parent_workflow_id": parent_handle.workflow_id,
            "__execution_timeout_s": (
                execution_timeout.total_seconds() if execution_timeout else None
            ),
            **input,
        }
        instance_id = await self._state_store.create(
            workflow_name=workflow_name,
            route_id=workflow_name,
            input_payload=payload,
            tenant_id=tenant_id,
        )
        return WorkflowHandle(
            workflow_id=workflow_id,
            run_id=instance_id.hex,
            namespace=parent_handle.namespace,
        )

    # --- helpers -------------------------------------------------------

    @staticmethod
    def _uuid_from_handle(handle: WorkflowHandle) -> UUID:
        """Достать UUID instance.id из ``handle.run_id`` (hex)."""
        try:
            return UUID(hex=handle.run_id)
        except ValueError as exc:
            raise ValueError(
                f"invalid run_id={handle.run_id!r}: not a UUID hex"
            ) from exc

    @staticmethod
    def _row_to_result(row: WorkflowInstanceRow) -> WorkflowResult:
        """Маппинг ``WorkflowInstanceRow`` → ``WorkflowResult``."""
        snapshot = dict(row.snapshot_state or {})
        last_error = snapshot.pop("last_error", None) if snapshot else None
        failure: dict[str, Any] | None = None
        if row.status is WorkflowStatus.failed:
            failure = {"type": "WorkflowFailure", "message": last_error or ""}
        elif row.status is WorkflowStatus.cancelled:
            failure = {"type": "Cancelled", "message": last_error or ""}
        return WorkflowResult(
            output=snapshot, status=_status_to_protocol(row.status), failure=failure
        )
