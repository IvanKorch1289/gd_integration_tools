"""S107 W3 — ``core.audit.facade.waf``: WAF evaluation audit.

Per-domain helper (S106 W2 Path A pattern A, WAF-specific).
Used by ``core/net/outbound_http.py``.
Translates ``WafDecision`` (host, allowed, reason) + outbound context.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.audit.facade._base import emit_audit

__all__ = ("emit_waf_evaluation",)


def emit_waf_evaluation(
    *,
    decision: Any,
    plugin: str,
    method: str,
    url: str,
) -> Any:
    """Emit audit event for WAF evaluation (Path A pattern A, WAF-specific).

    Used by ``core/net/outbound_http.py``. Translates ``WafDecision``
    (host, allowed, reason) + outbound context to canonical kwargs.

    Args:
        decision: ``WafDecision`` (host, allowed, reason).
        plugin: WAF plugin name (``"core.waf"``).
        method: HTTP method (``"GET"``).
        url: Target URL.

    Returns:
        Result of ``AuditService.emit()``.
    """
    details: dict[str, Any] = {
        "plugin": plugin,
        "method": method,
        "url": url,
        "host": getattr(decision, "host", None),
        "allowed": getattr(decision, "allowed", None),
        "reason": getattr(decision, "reason", None),
    }
    return emit_audit(
        event="waf.evaluate",
        actor=plugin,
        resource=url,
        action=method,
        outcome="success" if details["allowed"] else "denied",
        details=details,
    )
