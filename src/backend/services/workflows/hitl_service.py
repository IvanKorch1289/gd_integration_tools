"""HITL (Human-in-the-Loop) service (Sprint 9 K3 W2).

DoD-4: backend-сервис для panel-управления pending workflow-сигналами.
Pattern:

#. Workflow ставится на ``wait_signal("hitl_approve")`` (Temporal nativeAPI).
#. Через :class:`HitlService` operator получает список pending workflows
   с metadata (initiator, requested_at, payload preview).
#. Operator вызывает :meth:`approve` или :meth:`reject` — signal
   отправляется в workflow через :class:`WorkflowFacade`.
#. Workflow продолжает / откатывается.

In-memory backend для dev_light; production реализует
:class:`HitlSignalStore` через Redis hash или Postgres table.

Sprint 178 (HITL-1 ARC-010 closeout): :meth:`HitlService.resolve`
дополнительно publishes в Redis pub/sub (per-tenant channel
``hitl:resolved:{tenant_id}`` через :mod:`hitl_pubsub`). Это
**additive notification** для cross-instance consumers
(см. :mod:`hitl_pubsub_consumer`) — in-memory waiter продолжает
работать. Failure в publish НЕ ломает resolve (best-effort).

S3 (ledger, 2026-09-05): сплит god-object (507 LOC). Модели —
:mod:`hitl_models`, хранилище — :mod:`hitl_signal_store`; этот модуль —
тонкий оркестратор. Re-exports сохраняют обратную совместимость всех
импортов ``from ...hitl_service import ...``.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.services.workflows.hitl_models import HitlAction, HitlPendingSignal
from src.backend.services.workflows.hitl_signal_store import (
    HitlSignalStore,
    InMemoryHitlSignalStore,
)

__all__ = (
    "HitlAction",
    "HitlPendingSignal",
    "HitlService",
    "HitlSignalStore",
    "InMemoryHitlSignalStore",
)


# Cycle 73 L6: module-level canonical logger (was: inline
# logging.getLogger(...)/get_logger(...) scattered).
_logger = get_logger("services.workflows.hitl")


class HitlService:
    """Orchestrator: store + workflow_facade.

    Args:
        store: :class:`HitlSignalStore` (любая реализация).
        workflow_facade: опц. :class:`WorkflowFacade`. Если None — signal
            не отправляется (используется в e2e-тестах с фейковым backend'ом).
        caller_name: используется как ``caller`` для CapabilityGate.

    """

    def __init__(
        self,
        *,
        store: HitlSignalStore,
        workflow_facade: Any = None,
        caller_name: str = "hitl_service",
    ) -> None:
        self._store = store
        self._facade = workflow_facade
        self._caller = caller_name

    async def register_pending(self, signal: HitlPendingSignal) -> None:
        """Register a pending signal (called by workflow activity).

        Args:
            signal: Pending signal to register.

        """
        await self._store.put(signal)

    async def list_pending(
        self, *, tenant_id: str | None = None
    ) -> list[HitlPendingSignal]:
        """List pending signals.

        Args:
            tenant_id: Optional tenant filter.

        Returns:
            List of pending signals.

        """
        return await self._store.list_pending(tenant_id=tenant_id)

    async def get(self, signal_id: str) -> HitlPendingSignal | None:
        """Get signal by ID.

        Args:
            signal_id: Signal identifier.

        Returns:
            Signal if found, None otherwise.

        """
        return await self._store.get(signal_id)

    async def wait_for(self, signal_id: str, timeout: float | None = None) -> bool:
        """Wait for signal resolution.

        Args:
            signal_id: Signal identifier.
            timeout: Optional timeout in seconds.

        Returns:
            True if resolved, False if timeout.

        """
        return await self._store.wait_for(signal_id, timeout=timeout)

    async def resolve(
        self,
        *,
        signal_id: str,
        action: str,
        resolved_by: str,
        payload: dict[str, Any] | None = None,
    ) -> HitlPendingSignal:
        """Resolve a pending HITL signal.

        Args:
            signal_id: Signal identifier.
            action: Resolution action (approve/reject/request_info).
            resolved_by: Operator name.
            payload: Optional additional data.

        Returns:
            Updated HitlPendingSignal.

        Raises:
            ValueError: If invalid action or signal already resolved.

        """
        if action not in HitlAction.all():
            raise ValueError(f"Invalid action {action!r}; allowed: {HitlAction.all()}")
        resolved = await self._store.mark_resolved(
            signal_id, action=action, resolved_by=resolved_by
        )
        await self._publish_resolved(resolved, action, resolved_by, payload)
        await self._signal_workflow(resolved, action, resolved_by, payload)
        await self._emit_audit(signal_id, resolved, action, resolved_by, payload)
        return resolved

    async def _publish_resolved(
        self,
        resolved: HitlPendingSignal,
        action: str,
        resolved_by: str,
        payload: dict[str, Any] | None,
    ) -> None:
        """S178 HITL-1: cross-instance notification (best-effort)."""
        try:
            from src.backend.services.workflows.hitl_pubsub import publish_hitl_resolved

            await publish_hitl_resolved(
                signal_id=resolved.signal_id,
                workflow_id=resolved.workflow_id,
                tenant_id=resolved.tenant_id,
                action=action,
                resolved_by=resolved_by,
                payload=payload or {},
            )
        except Exception as exc:
            # Ponytail: in-memory waiter works; pub/sub failure → log only.
            _logger.warning(
                "hitl.pubsub.publish_failed signal_id=%s: %s "
                "(in-memory waiter continues, see hitl_pubsub_consumer "
                "for cross-instance consumer)",
                resolved.signal_id,
                exc,
            )

    async def _signal_workflow(
        self,
        resolved: HitlPendingSignal,
        action: str,
        resolved_by: str,
        payload: dict[str, Any] | None,
    ) -> None:
        """Signal в workflow через facade (если configured)."""
        if self._facade is None:
            return
        from src.backend.core.workflow.backend import WorkflowHandle

        handle = WorkflowHandle(
            workflow_id=resolved.workflow_id,
            run_id=resolved.signal_id,
            namespace=resolved.tenant_id,
        )
        await self._facade.signal(
            caller=self._caller,
            handle=handle,
            signal_name=resolved.signal_name,
            payload={
                "action": action,
                "resolved_by": resolved_by,
                "data": payload or {},
            },
        )

    async def _emit_audit(
        self,
        signal_id: str,
        resolved: HitlPendingSignal,
        action: str,
        resolved_by: str,
        payload: dict[str, Any] | None,
    ) -> None:
        """Audit-sink emit (best-effort, кроме скрытых багов)."""
        try:
            from src.backend.services.audit.workflow_audit_sink import (
                get_workflow_audit_sink,
            )

            sink = get_workflow_audit_sink()
            if sink is None:
                return
            action_map = {
                HitlAction.APPROVE: "hitl.approved",
                HitlAction.REJECT: "hitl.rejected",
                HitlAction.REQUEST_INFO: "hitl.requested_info",
            }
            event_type = action_map.get(action, f"hitl.{action}")
            duration_ms: int | None = None
            if resolved.resolved_at and resolved.created_at:
                delta = resolved.resolved_at - resolved.created_at
                duration_ms = int(delta.total_seconds() * 1000)
            await sink.emit(
                event_type=event_type,
                workflow_id=resolved.workflow_id,
                tenant_id=resolved.tenant_id,
                actor=resolved_by,
                duration_ms=duration_ms,
                payload={
                    "signal_id": signal_id,
                    "action": action,
                    "comment": (payload or {}).get("comment"),
                },
            )
        except (ImportError, AttributeError, RuntimeError) as exc:
            # Audit-sink best-effort: не должен ломать HITL-resolve.
            # Раньше было except Exception: pass — скрывало баги (V22 K-OP-1).
            _logger.warning(
                "audit sink emit failed for signal_id=%s: %s", signal_id, exc
            )
