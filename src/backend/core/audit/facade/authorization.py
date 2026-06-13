"""S107 W3 — ``core.audit.facade.authorization``: authorization decision audit.

Per-domain helper (S106 W2 Path A pattern A). Used by
``core/security/authorization_gateway/audit_mixin.py``.
Translates ``AuthorizationDecision`` to canonical kwargs.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.audit.facade._base import emit_audit

__all__ = ("emit_authorization_decision",)


def emit_authorization_decision(
    *,
    decision: Any,
    principal: str,
    resource: str,
    action: str = "authorize",
) -> Any:
    """Emit audit event for authorization decision (Path A pattern A).

    Used by ``core/security/authorization_gateway/audit_mixin.py``.
    Translates ``AuthorizationDecision`` to canonical kwargs.

    Args:
        decision: ``AuthorizationDecision`` dataclass (allowed, reason,
            matched_policy, scope_checked, evaluated_at).
        principal: Who attempted (``"user:alice"``).
        resource: Target resource identifier.
        action: Action attempted (default ``"authorize"``).

    Returns:
        Result of ``AuditService.emit()``.
    """
    details: dict[str, Any] = {
        "allowed": getattr(decision, "allowed", None),
        "reason": getattr(decision, "reason", None),
        "matched_policy": getattr(decision, "matched_policy", None),
        "scope_checked": getattr(decision, "scope_checked", None),
        "evaluated_at": str(getattr(decision, "evaluated_at", "")),
    }
    return emit_audit(
        event="authorization.decision",
        actor=principal,
        resource=resource,
        action=action,
        outcome="success" if details["allowed"] else "denied",
        details=details,
    )
