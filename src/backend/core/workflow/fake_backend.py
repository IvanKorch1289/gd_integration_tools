"""`FakeWorkflowBackend` — in-memory реализация `WorkflowBackend`.

Wave C scaffold. Используется в unit-тестах core / services, где
поведение конкретного движка не критично, нужен только контракт
Protocol'а.

Хранит состояние в `dict[run_id, _Instance]`; сигналы / queries /
cancel работают без сети. Не предназначен для production —
завершение `await_completion` возвращается мгновенно с
заранее сконфигурированным результатом или дефолтным
``status="completed", output={}``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.backend.core.workflow.backend import (
    WorkflowBackend,
    WorkflowHandle,
    WorkflowResult,
)

__all__ = ("FakeWorkflowBackend",)


class _Instance(BaseModel):
    """Внутреннее состояние одного fake-инстанса."""

    model_config = ConfigDict(extra="forbid")

    handle: WorkflowHandle
    workflow_name: str
    input: dict[str, Any]
    task_queue: str
    execution_timeout: timedelta | None = None
    signals: list[tuple[str, dict[str, Any]]] = Field(default_factory=list)
    cancelled: bool = False
    result: WorkflowResult | None = None
    parent_run_id: str | None = None


class FakeWorkflowBackend(WorkflowBackend):
    """In-memory backend без сети и таймеров."""

    def __init__(
        self,
        *,
        default_result: WorkflowResult | None = None,
        query_handlers: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Параметры теста:

        :param default_result: возвращается из ``await_completion`` для
            ещё незавершённых инстансов (по умолчанию — ``status="completed"``).
        :param query_handlers: статичные ответы для ``query_workflow`` по
            имени query.
        """
        self._instances: dict[str, _Instance] = {}
        self._default_result = default_result or WorkflowResult(status="completed")
        self._query_handlers = query_handlers or {}

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
        """Зарегистрировать новый fake-инстанс и вернуть дескриптор."""
        run_id = uuid4().hex
        handle = WorkflowHandle(
            workflow_id=workflow_id, run_id=run_id, namespace=namespace,
        )
        self._instances[run_id] = _Instance(
            handle=handle,
            workflow_name=workflow_name,
            input=input,
            task_queue=task_queue,
            execution_timeout=execution_timeout,
        )
        return handle

    async def signal_workflow(
        self, *, handle: WorkflowHandle, signal_name: str, payload: dict[str, Any],
    ) -> None:
        """Записать сигнал в журнал инстанса."""
        instance = self._require(handle)
        instance.signals.append((signal_name, payload))

    async def query_workflow(
        self,
        *,
        handle: WorkflowHandle,
        query_name: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Вернуть статичный ответ из ``query_handlers`` или ``{}``."""
        self._require(handle)
        return self._query_handlers.get(query_name, {})

    async def cancel_workflow(self, *, handle: WorkflowHandle) -> None:
        """Пометить инстанс как ``cancelled``."""
        instance = self._require(handle)
        instance.cancelled = True
        instance.result = WorkflowResult(status="cancelled")

    async def await_completion(
        self, *, handle: WorkflowHandle, timeout: timedelta | None = None,
    ) -> WorkflowResult:
        """Вернуть сохранённый результат либо `default_result`."""
        instance = self._require(handle)
        if instance.result is not None:
            return instance.result
        return self._default_result

    async def replay(self, *, workflow_name: str, history: bytes) -> None:
        """No-op: fake не моделирует replay-семантику."""
        return

    async def await_external_signal(
        self,
        *,
        handle: WorkflowHandle,
        signal_name: str,
        timeout: timedelta | None = None,
    ) -> dict[str, Any]:
        """Fake: проверить, был ли сигнал доставлен ранее.

        ``signal_workflow`` для fake-инстанса всегда доставляет мгновенно
        (записывает в ``instance.signals``), поэтому ``await_external_signal``
        возвращает payload сразу. Если сигнал ещё не был доставлен —
        ``{"timed_out": True}``.
        """
        instance = self._require(handle)
        for name, payload in reversed(instance.signals):
            if name == signal_name:
                return payload
        return {"timed_out": True}

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
        """Fake: зарегистрировать child как новый fake-инстанс.

        Namespace наследуется от parent (multi-tenant consistency).
        Parent linkage сохраняется в ``_Instance.parent_run_id`` для
        тестов cancellation cascade.
        """
        parent = self._require(parent_handle)
        run_id = uuid4().hex
        handle = WorkflowHandle(
            workflow_id=workflow_id,
            run_id=run_id,
            namespace=parent.handle.namespace,
        )
        self._instances[run_id] = _Instance(
            handle=handle,
            workflow_name=workflow_name,
            input=input,
            task_queue=task_queue,
            execution_timeout=execution_timeout,
        )
        # Сохранить parent linkage для cancellation cascade.
        self._instances[run_id].parent_run_id = parent.handle.run_id  # type: ignore[attr-defined]
        return handle

    # --- helpers для тестов ---------------------------------------------

    def set_result(self, handle: WorkflowHandle, result: WorkflowResult) -> None:
        """Подменить результат конкретного инстанса (test-helper)."""
        self._require(handle).result = result

    def signals_for(self, handle: WorkflowHandle) -> list[tuple[str, dict[str, Any]]]:
        """Журнал сигналов конкретного инстанса (test-helper)."""
        return list(self._require(handle).signals)

    def is_cancelled(self, handle: WorkflowHandle) -> bool:
        """Был ли инстанс отменён (test-helper)."""
        return self._require(handle).cancelled

    def _require(self, handle: WorkflowHandle) -> _Instance:
        instance = self._instances.get(handle.run_id)
        if instance is None:
            raise KeyError(f"Unknown fake workflow run_id={handle.run_id!r}")
        if instance.handle != handle:
            raise ValueError(
                f"Handle mismatch for run_id={handle.run_id!r}: "
                f"stored={instance.handle!r}, given={handle!r}",
            )
        return instance
