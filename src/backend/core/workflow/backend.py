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
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
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
        self, *, handle: WorkflowHandle, signal_name: str, payload: dict[str, Any]
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
        """Отменить выполняющийся workflow."""
        ...

    async def await_completion(
        self, *, handle: WorkflowHandle, timeout: timedelta | None = None
    ) -> WorkflowResult:
        """Дождаться финального состояния workflow."""
        ...

    async def replay(self, *, workflow_name: str, history: bytes) -> None:
        """Прогнать историю через текущий код — для CI versioning gate."""
        ...
