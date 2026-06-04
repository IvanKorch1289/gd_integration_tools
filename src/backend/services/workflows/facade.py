"""`WorkflowFacade` — capability-gated фасад над `WorkflowBackend`.

ADR-045 §«Capability integration»: route, стартующий workflow,
декларирует `workflow.start` / `workflow.signal` capabilities в
`route.toml`. Этот facade:

1. Принимает имя плагина/route'а как ``caller`` argument.
2. Дёргает :class:`CapabilityGate` перед каждым вызовом backend.
3. Прокидывает остальные параметры в backend без модификации.
4. После успешного backend-вызова отправляет событие в
   :class:`WorkflowAuditSink` (если зарегистрирован). Ошибка emit
   логируется warning'ом и не ломает основной workflow-flow.

Плагины НЕ должны импортировать ``WorkflowBackend`` напрямую — только
через ``WorkflowFacade`` (через DI). Это даёт audit-trail и blast-radius
control: capability denied → исключение, попытка фиксируется в audit.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from src.backend.core.security.capabilities import CapabilityGate
from src.backend.core.workflow.backend import (
    WorkflowBackend,
    WorkflowHandle,
    WorkflowResult,
)

if TYPE_CHECKING:
    from src.backend.services.audit.workflow_audit_sink import WorkflowAuditSink

__all__ = ("WorkflowFacade",)

_logger = logging.getLogger("services.workflows.facade")


class WorkflowFacade:
    """Capability-gated wrapper над `WorkflowBackend`.

    Args:
        backend: реализация :class:`WorkflowBackend` (Temporal или Lite).
        capability_gate: :class:`CapabilityGate` для проверки прав caller'а.
        audit_sink: опц. :class:`WorkflowAuditSink`. Если ``None`` —
            audit-emit пропускается (no-op). emit-фейлы поглощаются
            ``try/except logger.warning``.
    """

    def __init__(
        self,
        *,
        backend: WorkflowBackend,
        capability_gate: CapabilityGate,
        audit_sink: WorkflowAuditSink | None = None,
    ) -> None:
        self._backend = backend
        self._gate = capability_gate
        self._audit_sink = audit_sink

    async def _emit(
        self,
        *,
        event_type: str,
        workflow_id: str,
        caller: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Best-effort emit события в audit sink (no-op если sink=None).

        Никогда не пробрасывает исключения — каждая ошибка логируется
        warning'ом, чтобы пропадание audit-связи не ломало основной
        workflow.
        """
        sink = self._audit_sink
        if sink is None:
            return
        try:
            await sink.emit(
                event_type=event_type,
                workflow_id=workflow_id,
                tenant_id=None,
                payload={"caller": caller, **(payload or {})},
            )
        except Exception as exc:
            _logger.warning(
                "workflow_audit.emit_failed",
                extra={
                    "event_type": event_type,
                    "workflow_id": workflow_id,
                    "error": str(exc)[:200],
                },
            )

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
        handle = await self._backend.start_workflow(
            workflow_name=workflow_name,
            workflow_id=workflow_id,
            input=input,
            namespace=namespace,
            task_queue=task_queue,
            execution_timeout=execution_timeout,
        )
        await self._emit(
            event_type="workflow.start",
            workflow_id=workflow_id,
            caller=caller,
            payload={"workflow_name": workflow_name, "namespace": namespace},
        )
        return handle

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
        await self._emit(
            event_type="workflow.signal",
            workflow_id=handle.workflow_id,
            caller=caller,
            payload={"signal_name": signal_name},
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
        result = await self._backend.query_workflow(
            handle=handle, query_name=query_name, args=args
        )
        await self._emit(
            event_type="workflow.query",
            workflow_id=handle.workflow_id,
            caller=caller,
            payload={"query_name": query_name},
        )
        return result

    async def cancel(self, *, caller: str, handle: WorkflowHandle) -> None:
        """Cancel workflow — требует ``workflow.signal`` (semantically близко)."""
        self._gate.check(caller, "workflow.signal", handle.workflow_id)
        await self._backend.cancel_workflow(handle=handle)
        await self._emit(
            event_type="workflow.cancel", workflow_id=handle.workflow_id, caller=caller
        )

    async def await_completion(
        self, *, handle: WorkflowHandle, timeout: timedelta | None = None
    ) -> WorkflowResult:
        """Read-only ожидание completion — capability check не нужен.

        Кто запустил workflow, тот может узнать его финал через
        handle (никакого side-effect'а на чужой workflow).
        """
        return await self._backend.await_completion(handle=handle, timeout=timeout)
