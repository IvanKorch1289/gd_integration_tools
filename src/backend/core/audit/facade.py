"""S103 W3 — Audit facade canonical location.

DEEP-RESEARCH §3.4 claim "9 audit files (split-brain 🟡)" — частично
УСТАРЕВШИЙ. Фасад ``AuditService`` уже существует (Sprint 16 Wave 8,
S62 ADR-0179 partial closure). 16 users уже мигрированы на
``get_unified_audit_service()``.

S103 W3 делает canonical location для facade:
* Re-export из ``services/audit/audit_service.py`` через
  ``core/audit/facade.py`` — stable import path (аналогично S95 W4
  AuthGateway pattern: ``core/auth/gateway.py``).
* Migration: 16 уже фасад-users, 58 legacy ``_emit_audit`` callsites
  остаются (S103+ W4+ backlog — multi-wave migration).
* AuditService facade signature documented в services/audit/audit_service.py
  module docstring.

Этот файл — minimum 1-commit W3 work: stable canonical import path.
Real consolidation (58 callsites → facade) = S103+ W4+ backlog.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

# Canonical re-exports — аналогично S95 W4 AuthGateway pattern.
from src.backend.services.audit.audit_service import (  # noqa: F401
    AuditService,
    get_unified_audit_service,
)

if TYPE_CHECKING:
    pass

__all__ = (
    "AuditService",
    "get_unified_audit_service",
)


def emit_audit(
    event: str,
    *,
    actor: str = "system",
    resource: str = "",
    action: str = "",
    outcome: str = "success",
    details: dict[str, Any] | None = None,
) -> Any:
    """Canonical facade method — emit audit event (sync wrapper).

    S103 W3: re-export ``AuditService.emit()`` через canonical location.
    Async-версия ``audit_service.emit()`` (для использования внутри
    async-контекстов) — preferred. Этот sync wrapper exists для
    ``__init__``/module-level calls (e.g. ``emit_audit(event='boot')``).

    Args:
        event: Имя события (``"feature.toggled"``).
        actor: Кто выполнил (``"admin:alice"`` или ``"system"``).
        resource: Ресурс (например, ``"feature_flag/ai_workspace_ttl"``).
        action: Действие (``"toggle"``, ``"create"``, ``"delete"``).
        outcome: Результат (``"success"`` / ``"failure"`` / ``"denied"``).
        details: Доп. metadata (dict).

    Returns:
        Результат ``AuditService.emit()`` (None или coroutine в async ctx).
    """
    svc = get_unified_audit_service()
    return svc.emit(  # type: ignore[no-untyped-call]
        event=event,
        actor=actor,
        resource=resource,
        action=action,
        outcome=outcome,
        details=details,
    )
