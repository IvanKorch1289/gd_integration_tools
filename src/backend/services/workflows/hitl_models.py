"""HITL модели: допустимые действия и pending-сигнал (S3 сплит, из hitl_service).

S3 (ledger, 2026-09-05): выделение зон ответственности из
``hitl_service.py`` (507 LOC god-object) по паттерну закрытых M2-сплитов.
Обратная совместимость — ``hitl_service`` ре-экспортирует публичные имена.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

__all__ = ("HitlAction", "HitlPendingSignal")


class HitlAction:
    """Допустимые операторские действия."""

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_INFO = "request_info"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        """Get all HITL action types.

        Returns:
            Tuple of action type strings.

        """
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
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    resolved_action: str | None = None
    resolved_by: str | None = None

    @property
    def is_resolved(self) -> bool:
        """Check if signal is resolved.

        Returns:
            True if resolved, False if pending.

        """
        return self.resolved_at is not None

    def to_dict(self) -> dict[str, Any]:
        """Convert signal to dictionary.

        Returns:
            Dictionary representation.

        """
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HitlPendingSignal:
        """S207: reconstruct from :meth:`to_dict` (для Redis/JSON deserialization).

        Args:
            data: Dict из :meth:`to_dict` (например из Redis hash value).

        Returns:
            Новый :class:`HitlPendingSignal` инстанс.

        """
        from datetime import datetime as _dt

        created_raw = data.get("created_at")
        created = _dt.fromisoformat(created_raw) if created_raw else _dt.now(UTC)
        resolved_raw = data.get("resolved_at")
        resolved = _dt.fromisoformat(resolved_raw) if resolved_raw else None
        return cls(
            signal_id=data["signal_id"],
            workflow_id=data["workflow_id"],
            tenant_id=data["tenant_id"],
            signal_name=data["signal_name"],
            initiator=data["initiator"],
            title=data["title"],
            payload=data.get("payload") or {},
            created_at=created,
            resolved_at=resolved,
            resolved_action=data.get("resolved_action"),
            resolved_by=data.get("resolved_by"),
        )
