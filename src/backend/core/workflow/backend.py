"""ADR-045 — `WorkflowBackend` Protocol + Pydantic-модели.

Wave C scaffold: контракт workflow-движка для ядра. Конкретные
реализации (`TemporalWorkflowBackend`, `PgRunnerWorkflowBackend`)
живут в `infrastructure/workflow/` и подключаются через DI.

Ядро видит только Protocol — это позволяет:
- тестировать pipeline через `FakeWorkflowBackend`;
- переключать default backend (Temporal) и fallback (pg-runner)
  через DI без правок core / services;
- держать dev-light без Temporal-кластера.

См. ADR-045 §«WorkflowBackend Protocol».
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("WorkflowBackend", "WorkflowHandle", "WorkflowResult", "WorkflowStatus")


WorkflowStatus = str
"""Финальный статус workflow: ``completed | failed | cancelled | timed_out``.

Литеральный набор не зашит в Pydantic-моделях, чтобы конкретный backend
мог использовать собственные расширенные значения (Temporal Build IDs
и пр.); ядро интерпретирует только базовую четвёрку.
"""


class WorkflowHandle(BaseModel):
    """Дескриптор запущенного workflow-инстанса.

    `namespace` хранит tenant-id (multi-tenant) или ``"global"`` для
    cross-tenant supervisors. `run_id` — backend-specific идентификатор
    конкретного запуска (Temporal run-id / pg-runner instance-id).

    D-A8-09 fix (cycle 24): `run_id` опциональный — None означает
    "cancel/signal/query all runs of this workflow_id" (Temporal cancel
    semantics при ``run_id=None``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: str = Field(min_length=1)
    run_id: str | None = Field(default=None)
    namespace: str = Field(min_length=1)


class WorkflowResult(BaseModel):
    """Финальный результат `await_completion()`.

    `failure` присутствует только для `status in {failed, timed_out,
    cancelled}` и содержит сериализованную причину
    (`{"type": "...", "message": "...", "details": {...}}`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    output: dict[str, Any] = Field(default_factory=dict)
    status: WorkflowStatus
    failure: dict[str, Any] | None = None


@runtime_checkable
class WorkflowBackend(Protocol):
    """Унифицированный контракт workflow-движка для ядра."""

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
        """Запустить workflow-инстанс и вернуть его дескриптор."""
        ...

    async def signal_workflow(
        self, *, handle: WorkflowHandle, signal_name: str, payload: dict[str, Any],
    ) -> None:
        """Отправить сигнал работающему workflow."""
        ...

    async def query_workflow(
        self,
        *,
        handle: WorkflowHandle,
        query_name: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Синхронный typed-query к workflow (read-only)."""
        ...

    async def cancel_workflow(self, *, handle: WorkflowHandle) -> None:
        """Отменить выполняющийся workflow (cancel через backend API)."""
        ...

    async def await_completion(
        self, *, handle: WorkflowHandle, timeout: timedelta | None = None,
    ) -> WorkflowResult:
        """Дождаться финального состояния workflow."""
        ...

    # S202 fix: compensate_workflow removed from Protocol.
    # Был объявлен, но НИ ОДИН backend (Temporal/LiteTemporal/PgRunner/Fake)
    # не реализовывал его. Saga compensation работает через COMPENSATE_SIGNAL
    # в compensation.py → compile_saga_step → DSL compiler.
    # Protocol method был unreachable dead contract (GAP-1 из аудита).

    async def replay(self, *, workflow_name: str, history: bytes) -> None:
        """Прогнать историю через текущий код — для CI versioning gate."""
        ...

    # S210 fix: HITL/subworkflow support (REPORT.md gap #4).
    # До этого workflow мог обмениваться сигналами с внешним миром
    # только через ``signal_workflow`` (push), но не мог ждать
    # внешнего события (pull). Это ограничивало HITL-паттерн
    # (services/workflows/hitl_pubsub.py) — workflow не мог
    # приостановиться в ожидании решения оператора.
    #
    # ``await_external_signal`` закрывает этот пробел: workflow
    # объявляет ожидаемый сигнал + timeout, backend блокирует до
    # прихода сигнала или таймаута. Реализация для Temporal —
    # через ``workflow.await_signal()`` (native API). Для
    # LiteTemporal — идентично. Для PgRunner — через LISTEN/NOTIFY
    # + per-instance wait-queue. Для Fake — простой in-memory dict.

    async def await_external_signal(
        self,
        *,
        handle: WorkflowHandle,
        signal_name: str,
        timeout: timedelta | None = None,
    ) -> dict[str, Any]:
        """Приостановить workflow до получения внешнего сигнала или таймаута.

        Используется для HITL: workflow шлёт ``HumanTask`` оператору,
        затем ``await_external_signal`` ждёт решения (approval/reject/cancel).
        Returns payload сигнала; при таймауте — ``{"timed_out": True}``.

        Args:
            handle: Дескриптор ожидающего workflow.
            signal_name: Имя сигнала, которого ждём.
            timeout: Максимальное время ожидания (None = бесконечно).

        Returns:
            Payload сигнала (dict). При таймауте: ``{"timed_out": True}``.
        """
        ...

    # S210 fix: child workflow support (REPORT.md gap #4).
    # ``start_child_workflow`` запускает workflow как дочерний по
    # отношению к parent. Backend обязан прокинуть parent-context
    # (Temporal: ``parent_workflow_id`` / ``parent_run_id``) чтобы
    # child наследовал namespace + cancellation cascade.
    #
    # Реализация для Temporal: ``Client.start_workflow(..., parent=...)``.
    # Для LiteTemporal: ``WorkflowEnvironment.start_workflow(..., parent=...)``.
    # Для PgRunner: parent_workflow_id записывается в workflow_metadata
    # + cancellation через ``cancel_workflow`` cascade.
    # Для Fake: parent_workflow_id сохраняется в in-memory dict.

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
        """Запустить workflow как дочерний от parent.

        Args:
            parent_handle: Дескриптор parent workflow.
            workflow_name: Имя child workflow (из DSL/builder).
            workflow_id: Уникальный ID child workflow.
            input: Входные данные.
            task_queue: Task queue для child worker.
            execution_timeout: Таймаут выполнения.

        Returns:
            Дескриптор child workflow. Namespace наследуется от parent.
            При cancel parent — child тоже отменяется.
        """
        ...
