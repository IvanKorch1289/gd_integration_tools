"""S107 W3 — ``core.audit.facade.capability``: capability gate audit.

Per-domain helper (S106 W2 Path A pattern B — highest traffic).
Used by ``core/security/capabilities/gate/audit_mixin.py`` — 17
inherited callsites в ``check_mixin.py`` + ``declaration_mixin.py``.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.audit.facade._base import emit_audit

__all__ = ("emit_capability_check",)


def emit_capability_check(
    *,
    plugin: str,
    capability: str,
    requested_scope: str | None,
    declared_scope: str | None,
    outcome: str,
    tenant: str | None = None,
    reason: str | None = None,
    event: str = "capability.check",
) -> Any:
    """Emit audit event for capability gate (Path A pattern B — highest traffic).

    Used by ``core/security/capabilities/gate/audit_mixin.py`` — 17 inherited
    callsites в ``check_mixin.py`` + ``declaration_mixin.py``.
    Translates capability-specific kwargs to canonical facade.

    Args:
        plugin: Plugin/route name.
        capability: Capability being checked (``db.read``).
        requested_scope: Scope requested at runtime.
        declared_scope: Scope declared in plugin manifest.
        outcome: ``"granted"`` / ``"denied"`` / ``"error"``.
        tenant: Optional tenant ID (tenant-aware paths).
        reason: Optional deny reason (``"policy"``, ``"scope_mismatch"``).
        event: Event name (default ``"capability.check"``; also
            ``"capability.allocated"``, ``"capability.revoked"``).

    Returns:
        Result of ``AuditService.emit()``.
    """
    details: dict[str, Any] = {
        "plugin": plugin,
        "capability": capability,
        "requested_scope": requested_scope,
        "declared_scope": declared_scope,
    }
    if tenant is not None:
        details["tenant"] = tenant
    if reason is not None:
        details["reason"] = reason
    return emit_audit(
        event=event,
        actor=plugin,
        resource=capability,
        action="check",
        outcome=outcome,
        details=details,
    )
