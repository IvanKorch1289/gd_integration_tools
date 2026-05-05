"""`WorkflowFacade` — capability-gated фасад над `WorkflowBackend`.

ADR-045 §«Capability integration»: route, стартующий workflow,
декларирует `workflow.start` / `workflow.signal` capabilities в
`route.toml`. Этот facade:

1. Принимает имя плагина/route'а как ``caller`` argument.
2. Дёргает :class:`CapabilityGate` перед каждым вызовом backend.
3. Прокидывает остальные параметры в backend без модификации.

Плагины НЕ должны импортировать ``WorkflowBackend`` напрямую — только
через ``WorkflowFacade`` (через DI). Это даёт audit-trail и blast-radius
control: capability denied → исключение, попытка фиксируется в audit.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from src.core.security.capabilities import CapabilityGate
from src.core.workflow.backend import WorkflowBackend, WorkflowHandle, WorkflowResult

__all__ = ("WorkflowFacade",)


class WorkflowFacade:
    """Capability-gated wrapper над `WorkflowBackend`."""

    def __init__(
        self, *, backend: WorkflowBackend, capability_gate: CapabilityGate
    ) -> None:
        self._backend = backend
        self._gate = capability_gate

    async def start(
        self,
        *,
        caller: str,
        workflow_name: str,
        workflow_id: str,
        input: dict[str, Any],
        namespace: str,
        task_queue: str,
        execution_timeout: timedelta | None = None,
    ) -> WorkflowHandle:
        """Стартовать workflow от имени плагина/route'а.

        :param caller: имя plugin'а / route'а (для capability lookup).
        :raises CapabilityDeniedError: если caller не задекларировал
            ``workflow.start`` или scope не покрывает ``workflow_id``.
        """
        self._gate.check(caller, "workflow.start", workflow_id)
        return await self._backend.start_workflow(
            workflow_name=workflow_name,
            workflow_id=workflow_id,
            input=input,
            namespace=namespace,
            task_queue=task_queue,
            execution_timeout=execution_timeout,
        )

    async def signal(
        self,
        *,
        caller: str,
        handle: WorkflowHandle,
        signal_name: str,
        payload: dict[str, Any],
    ) -> None:
        """Послать сигнал workflow от имени плагина/route'а."""
        self._gate.check(caller, "workflow.signal", handle.workflow_id)
        await self._backend.signal_workflow(
            handle=handle, signal_name=signal_name, payload=payload
        )

    async def query(
        self,
        *,
        caller: str,
        handle: WorkflowHandle,
        query_name: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Read-only typed-query.

        Использует `workflow.signal` capability — query семантически
        relate к signal'у (доступ к чужому workflow); separate
        ``workflow.query`` capability — TBD R3 (см. ADR-044 §opens).
        """
        self._gate.check(caller, "workflow.signal", handle.workflow_id)
        return await self._backend.query_workflow(
            handle=handle, query_name=query_name, args=args
        )

    async def cancel(self, *, caller: str, handle: WorkflowHandle) -> None:
        """Cancel workflow — требует ``workflow.signal`` (semantically близко)."""
        self._gate.check(caller, "workflow.signal", handle.workflow_id)
        await self._backend.cancel_workflow(handle=handle)

    async def await_completion(
        self, *, handle: WorkflowHandle, timeout: timedelta | None = None
    ) -> WorkflowResult:
        """Read-only ожидание completion — capability check не нужен.

        Кто запустил workflow, тот может узнать его финал через
        handle (никакого side-effect'а на чужой workflow).
        """
        return await self._backend.await_completion(handle=handle, timeout=timeout)
