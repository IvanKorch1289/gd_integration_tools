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
5. ADR-0396: SLA-политика workflow больше не инертна — hard-limit
   используется как бюджет времени (``execution_timeout``), а запущенный
   workflow ставится на SLA-трекинг (:class:`SlaTracker`).

Плагины НЕ должны импортировать ``WorkflowBackend`` напрямую — только
через ``WorkflowFacade`` (через DI). Это даёт audit-trail и blast-radius
control: capability denied → исключение, попытка фиксируется в audit.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.core.security.capabilities import CapabilityGate
from src.backend.core.workflow.backend import (
    WorkflowBackend,
    WorkflowHandle,
    WorkflowResult,
)
from src.backend.services.workflows.sla_alerting import SlaTracker

if TYPE_CHECKING:
    from src.backend.services.audit.workflow_audit_sink import WorkflowAuditSink

__all__ = ("WorkflowFacade", "SlaResolver")

_logger = get_logger("services.workflows.facade")

#: Резолвер SLA-политики по имени workflow (``None`` — политики нет).
#: Политика — объект с полями ``soft_limit_seconds`` /
#: ``hard_limit_seconds`` / ``escalation_email`` / ``escalation_slack`` /
#: ``breach_action`` (совместим с :class:`SlaPolicy` и
#: :class:`SlaTracker`).
SlaResolver = Callable[[str], Any | None]


class WorkflowFacade:
    """Capability-gated wrapper над `WorkflowBackend`.

    Args:
        backend: реализация :class:`WorkflowBackend` (Temporal или Lite).
        capability_gate: :class:`CapabilityGate` для проверки прав caller'а.
        audit_sink: опц. :class:`WorkflowAuditSink`. Если ``None`` —
            audit-emit пропускается (no-op). emit-фейлы поглощаются
            ``try/except logger.warning``.
        sla_tracker: опц. :class:`SlaTracker` — SLA-мониторинг запущенных
            workflow'ов (ADR-0396). Если ``None`` — трекинг пропускается.
        sla_resolver: опц. резолвер SLA-политики по имени workflow.
            Используется для бюджета времени (``execution_timeout``) и
            SLA-трекинга.

    """

    def __init__(
        self,
        *,
        backend: WorkflowBackend,
        capability_gate: CapabilityGate,
        audit_sink: WorkflowAuditSink | None = None,
        sla_tracker: SlaTracker | None = None,
        sla_resolver: SlaResolver | None = None,
    ) -> None:
        self._backend = backend
        self._gate = capability_gate
        self._audit_sink = audit_sink
        self._sla_tracker = sla_tracker
        self._sla_resolver = sla_resolver

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

        ADR-0396: если SLA-политика workflow'а найдена и явный
        ``execution_timeout`` не передан — используется SLA hard-limit как
        бюджет времени выполнения; запущенный workflow ставится на
        SLA-трекинг.

        :param caller: имя plugin'а / route'а (для capability lookup).
        :raises CapabilityDeniedError: если caller не задекларировал
            ``workflow.start`` или scope не покрывает ``workflow_id``.
        """
        self._gate.check(caller, "workflow.start", workflow_id)
        sla_policy = self._resolve_sla(workflow_name)
        timeout = execution_timeout
        if timeout is None and sla_policy is not None:
            # SLA hard-limit = бюджет времени workflow (ADR-0396).
            timeout = timedelta(seconds=float(sla_policy.hard_limit_seconds))
        handle = await self._backend.start_workflow(
            workflow_name=workflow_name,
            workflow_id=workflow_id,
            input=input,
            namespace=namespace,
            task_queue=task_queue,
            execution_timeout=timeout,
        )
        await self._track_sla(workflow_id=handle.workflow_id, sla=sla_policy)
        await self._emit(
            event_type="workflow.start",
            workflow_id=workflow_id,
            caller=caller,
            payload={"workflow_name": workflow_name, "namespace": namespace},
        )
        return handle

    def _resolve_sla(self, workflow_name: str) -> Any | None:
        """Найти SLA-политику workflow'а (None — политики нет)."""
        resolver = self._sla_resolver
        if resolver is None:
            return None
        try:
            return resolver(workflow_name)
        except Exception as exc:
            _logger.warning(
                "workflow_sla.resolve_failed",
                extra={"workflow_name": workflow_name, "error": str(exc)[:200]},
            )
            return None

    async def _track_sla(self, *, workflow_id: str, sla: Any | None) -> None:
        """Поставить workflow на SLA-трекинг (best-effort, no-op без трекера)."""
        tracker = self._sla_tracker
        if tracker is None or sla is None:
            return
        try:
            await tracker.track(workflow_id=workflow_id, sla=sla)
        except Exception as exc:
            _logger.warning(
                "workflow_sla.track_failed",
                extra={"workflow_id": workflow_id, "error": str(exc)[:200]},
            )

    async def _untrack_sla(self, *, workflow_id: str) -> None:
        """Снять workflow с SLA-трекинга (best-effort)."""
        tracker = self._sla_tracker
        if tracker is None:
            return
        try:
            await tracker.untrack(workflow_id)
        except Exception as exc:
            _logger.warning(
                "workflow_sla.untrack_failed",
                extra={"workflow_id": workflow_id, "error": str(exc)[:200]},
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

        ADR-0396: после завершения workflow снимается с SLA-трекинга.
        """
        result = await self._backend.await_completion(handle=handle, timeout=timeout)
        await self._untrack_sla(workflow_id=handle.workflow_id)
        return result
