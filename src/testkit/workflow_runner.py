"""WorkflowRunner — фасад для запуска workflow в тестах.

:class:`WorkflowRunner` оборачивает :class:`WorkflowFacade` или
:class:`FakeWorkflowBackend` для удобного запуска workflow в unit-тестах
без живого Temporal-кластера.

Этот модуль — часть ``src/testkit/`` public API (K5 S19 W3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from src.backend.core.workflow import FakeWorkflowBackend, WorkflowHandle
from src.backend.services.workflows.facade import WorkflowFacade

__all__ = ("WorkflowRunResult", "WorkflowRunner")


@dataclass(slots=True, frozen=True)
class WorkflowRunResult:
    """Результат запуска workflow через :class:`WorkflowRunner`."""

    workflow_id: str
    run_id: str
    namespace: str
    output: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"


class WorkflowRunner:
    """Запуск workflow в тестах через :class:`FakeWorkflowBackend`.

    Использует :class:`FakeWorkflowBackend` для in-memory выполнения
    без Temporal. Результат возвращается мгновенно.

    Args:
        default_status: статус по умолчанию для ``await_completion``.
            По умолчанию ``"completed"``.
        default_output: output по умолчанию для завершённых workflow.
        query_handlers: статичные ответы для query по имени.
    """

    def __init__(
        self,
        *,
        default_status: str = "completed",
        default_output: dict[str, Any] | None = None,
        query_handlers: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        from src.backend.core.workflow import WorkflowResult

        self._backend = FakeWorkflowBackend(
            default_result=WorkflowResult(
                status=default_status,
                output=default_output or {},
            ),
            query_handlers=query_handlers,
        )
        self._facade: WorkflowFacade | None = None

    @property
    def backend(self) -> FakeWorkflowBackend:
        """Доступ к underlying backend для advanced test scenarios."""
        return self._backend

    async def start(
        self,
        *,
        workflow_name: str,
        workflow_id: str,
        input: dict[str, Any] | None = None,
        namespace: str = "test",
        task_queue: str = "test-queue",
        execution_timeout: timedelta | None = None,
    ) -> WorkflowHandle:
        """Запустить workflow и вернуть :class:`WorkflowHandle`."""
        handle = await self._backend.start_workflow(
            workflow_name=workflow_name,
            workflow_id=workflow_id,
            input=input or {},
            namespace=namespace,
            task_queue=task_queue,
            execution_timeout=execution_timeout,
        )
        return handle

    async def run(
        self,
        *,
        workflow_name: str,
        workflow_id: str | None = None,
        input: dict[str, Any] | None = None,
        namespace: str = "test",
        task_queue: str = "test-queue",
        execution_timeout: timedelta | None = None,
    ) -> WorkflowRunResult:
        """Запустить workflow и дождаться результата.

        Это shorthand для ``start()`` + ``await_completion()``.
        """
        import uuid

        wf_id = workflow_id or f"test-wf-{uuid.uuid4().hex[:8]}"
        handle = await self.start(
            workflow_name=workflow_name,
            workflow_id=wf_id,
            input=input,
            namespace=namespace,
            task_queue=task_queue,
            execution_timeout=execution_timeout,
        )
        result = await self._backend.await_completion(handle=handle)
        return WorkflowRunResult(
            workflow_id=handle.workflow_id,
            run_id=handle.run_id,
            namespace=handle.namespace,
            output=result.output,
            status=result.status,
        )

    async def signal(
        self,
        *,
        handle: WorkflowHandle,
        signal_name: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Послать сигнал работающему workflow."""
        await self._backend.signal_workflow(
            handle=handle,
            signal_name=signal_name,
            payload=payload or {},
        )

    async def query(
        self,
        *,
        handle: WorkflowHandle,
        query_name: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Сделать query к workflow."""
        return await self._backend.query_workflow(
            handle=handle,
            query_name=query_name,
            args=args,
        )

    async def cancel(self, *, handle: WorkflowHandle) -> None:
        """Отменить workflow."""
        await self._backend.cancel_workflow(handle=handle)

    async def await_completion(
        self,
        *,
        handle: WorkflowHandle,
        timeout: timedelta | None = None,
    ) -> WorkflowRunResult:
        """Дождаться завершения workflow и вернуть результат."""
        result = await self._backend.await_completion(
            handle=handle,
            timeout=timeout,
        )
        return WorkflowRunResult(
            workflow_id=handle.workflow_id,
            run_id=handle.run_id,
            namespace=handle.namespace,
            output=result.output,
            status=result.status,
        )
