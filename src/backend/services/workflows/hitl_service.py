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
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

__all__ = (
    "HitlAction",
    "HitlPendingSignal",
    "HitlService",
    "HitlSignalStore",
    "InMemoryHitlSignalStore",
)


class HitlAction:
    """Допустимые операторские действия."""

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_INFO = "request_info"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return (cls.APPROVE, cls.REJECT, cls.REQUEST_INFO)


@dataclass(slots=True)
class HitlPendingSignal:
    """Pending HITL signal.

    Attributes:
        signal_id: уникальный идентификатор (для дедупликации actions).
        workflow_id: Temporal workflow ID.
        tenant_id: для filter по tenant.
        signal_name: имя сигнала в workflow (``hitl_approve``).
        initiator: кто запустил workflow.
        title: краткое описание (отображается в Streamlit таблице).
        payload: контекст для решения (документы, score, и т.п.).
        created_at: timestamp создания.
        resolved_at: timestamp разрешения (None если pending).
        resolved_action: :class:`HitlAction` или None.
        resolved_by: имя оператора, который разрешил.
    """

    signal_id: str
    workflow_id: str
    tenant_id: str
    signal_name: str
    initiator: str
    title: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
    resolved_action: str | None = None
    resolved_by: str | None = None

    @property
    def is_resolved(self) -> bool:
        return self.resolved_at is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "workflow_id": self.workflow_id,
            "tenant_id": self.tenant_id,
            "signal_name": self.signal_name,
            "initiator": self.initiator,
            "title": self.title,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
            "resolved_at": (self.resolved_at.isoformat() if self.resolved_at else None),
            "resolved_action": self.resolved_action,
            "resolved_by": self.resolved_by,
            "is_resolved": self.is_resolved,
        }


@runtime_checkable
class HitlSignalStore(Protocol):
    """Backend-агностичное хранилище pending signals."""

    async def put(self, signal: HitlPendingSignal) -> None: ...

    async def get(self, signal_id: str) -> HitlPendingSignal | None: ...

    async def list_pending(
        self, *, tenant_id: str | None = None
    ) -> list[HitlPendingSignal]: ...

    async def mark_resolved(
        self, signal_id: str, *, action: str, resolved_by: str
    ) -> HitlPendingSignal: ...


class InMemoryHitlSignalStore:
    """In-memory store для dev_light и unit-тестов."""

    def __init__(self) -> None:
        self._store: dict[str, HitlPendingSignal] = {}
        self._lock = asyncio.Lock()

    async def put(self, signal: HitlPendingSignal) -> None:
        async with self._lock:
            self._store[signal.signal_id] = signal

    async def get(self, signal_id: str) -> HitlPendingSignal | None:
        async with self._lock:
            return self._store.get(signal_id)

    async def list_pending(
        self, *, tenant_id: str | None = None
    ) -> list[HitlPendingSignal]:
        async with self._lock:
            items = [s for s in self._store.values() if not s.is_resolved]
        if tenant_id is not None:
            items = [s for s in items if s.tenant_id == tenant_id]
        return sorted(items, key=lambda s: s.created_at)

    async def mark_resolved(
        self, signal_id: str, *, action: str, resolved_by: str
    ) -> HitlPendingSignal:
        async with self._lock:
            signal = self._store.get(signal_id)
            if signal is None:
                raise KeyError(f"HITL signal {signal_id!r} not found")
            if signal.is_resolved:
                raise ValueError(
                    f"HITL signal {signal_id!r} already resolved by "
                    f"{signal.resolved_by!r} as {signal.resolved_action!r}"
                )
            signal.resolved_at = datetime.now(timezone.utc)
            signal.resolved_action = action
            signal.resolved_by = resolved_by
            return signal


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
        """Зафиксировать pending signal (вызывается workflow-activity).

        В реальном пайплайне эта запись делается activity'ом внутри
        Temporal workflow ДО ``wait_signal``.
        """
        await self._store.put(signal)

    async def list_pending(
        self, *, tenant_id: str | None = None
    ) -> list[HitlPendingSignal]:
        return await self._store.list_pending(tenant_id=tenant_id)

    async def get(self, signal_id: str) -> HitlPendingSignal | None:
        return await self._store.get(signal_id)

    async def resolve(
        self,
        *,
        signal_id: str,
        action: str,
        resolved_by: str,
        payload: dict[str, Any] | None = None,
    ) -> HitlPendingSignal:
        """Разрешить pending signal.

        Args:
            signal_id: идентификатор pending signal.
            action: :class:`HitlAction` (approve/reject/request_info).
            resolved_by: имя оператора.
            payload: опц. дополнительные данные (e.g. operator comment).

        Returns:
            Обновлённый :class:`HitlPendingSignal`.

        Raises:
            ValueError: invalid action или signal уже resolved.
            KeyError: signal_id не найден.
        """
        if action not in HitlAction.all():
            raise ValueError(f"Invalid action {action!r}; allowed: {HitlAction.all()}")
        resolved = await self._store.mark_resolved(
            signal_id, action=action, resolved_by=resolved_by
        )
        if self._facade is not None:
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

        try:
            from src.backend.services.audit.workflow_audit_sink import (
                get_workflow_audit_sink,
            )

            sink = get_workflow_audit_sink()
            if sink is not None:
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
        except Exception:  # noqa: BLE001
            pass

        return resolved
