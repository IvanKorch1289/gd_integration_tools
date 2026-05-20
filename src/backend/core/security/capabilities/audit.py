"""Sprint 14 K1 W4 — расширенный capability audit event.

Назначение:
    Структурированное событие, фиксирующее каждое решение
    :class:`CapabilityGate.check` — выдан ли запрошенный capability,
    причина отказа, какой tenant/actor запросил. Используется:

    1. ClickHouse sink (``infrastructure/sinks/audit_clickhouse.py``)
       для аудит-журнала grant/deny;
    2. Streamlit 71_Capabilities.py для вкладки "Audit log";
    3. SIEM-export (опционально).

Принципы:
    - frozen dataclass — событие иммутабельно после создания;
    - ``timestamp`` — UTC ISO-8601 ровно момент решения;
    - ``correlation_id`` — пробрасывается из middleware
      (entrypoints/middlewares/correlation_id.py).
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = (
    "CapabilityAuditEvent",
    "CapabilityAuditEventKind",
    "log_capability_event",
)

_logger = logging.getLogger("core.security.capabilities.audit")

CapabilityAuditEventKind = Literal["capability_grant", "capability_deny"]


@dataclass(frozen=True, slots=True)
class CapabilityAuditEvent:
    """Аудит-событие capability-проверки.

    Attributes:
        plugin: Имя плагина, запросившего capability.
        capability: Полное имя capability (``"db.read"`` и т.п.).
        scope: scope-аргумент проверки (``None`` если scope-less).
        granted: True — решение allow, False — deny.
        denial_reason: Причина отказа (``None`` при granted=True).
        tenant: tenant_id из TenantContext (``"_system"`` если отсутствует).
        actor: Identity актора (user/email/service-account) или
            ``"_anonymous"``.
        correlation_id: Request correlation_id для трассировки.
        timestamp: UTC момент решения в ISO-8601.
        extra: Произвольный словарь с дополнительным контекстом
            (например, route_id, action_id).
    """

    plugin: str
    capability: str
    scope: str | None
    granted: bool
    denial_reason: str | None = None
    tenant: str = "_system"
    actor: str = "_anonymous"
    correlation_id: str | None = None
    timestamp: str = field(
        default_factory=lambda: _dt.datetime.now(tz=_dt.UTC).isoformat(timespec="microseconds")
    )
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> CapabilityAuditEventKind:
        """``"capability_grant"`` или ``"capability_deny"``."""
        return "capability_grant" if self.granted else "capability_deny"

    def to_dict(self) -> dict[str, Any]:
        """JSON-сериализация для ClickHouse / SIEM."""
        return {
            "kind": self.kind,
            "plugin": self.plugin,
            "capability": self.capability,
            "scope": self.scope,
            "granted": self.granted,
            "denial_reason": self.denial_reason,
            "tenant": self.tenant,
            "actor": self.actor,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "extra": dict(self.extra),
        }


def log_capability_event(event: CapabilityAuditEvent) -> None:
    """Лог-helper — записывает структурированное событие в stdout-logger.

    Sink в ClickHouse подключается отдельно через
    :mod:`infrastructure.sinks.audit_clickhouse`.
    """
    _logger.info("capability_audit", extra={"event": event.to_dict()})
