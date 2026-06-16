"""S107 W3 — ``core.audit.facade.banking``: AI banking processor audit.

Per-domain helper (S106 W2 Path A pattern F).
Used by ``dsl/engine/processors/ai_banking/_audit.py`` (3 calls ×
3 banking files: credit, identity, document).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.audit.facade._base import emit_audit

__all__ = ("emit_banking_audit",)


def emit_banking_audit(
    event: str,
    processor: str,
    params: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> Any:
    """Emit audit event for AI banking processors (Path A pattern F).

    Used by ``dsl/engine/processors/ai_banking/_audit.py`` (3 calls ×
    3 banking files: credit, identity, document).

    Args:
        event: Event name (``"banking.kyc_aml.verify"``).
        processor: Processor name (``"credit"``, ``"identity"``).
        params: Input params (PII-safe — caller responsible для redact).
        result: Optional result dict.
        error: Optional error message.

    Returns:
        Result of ``AuditService.emit()``.
    """
    details: dict[str, Any] = {"processor": processor, "params": params}
    if result is not None:
        details["result"] = result
    outcome = "failure" if error is not None else "success"
    if error is not None:
        details["error"] = error
    return emit_audit(
        event=event,
        actor=processor,
        resource=event,
        action="process",
        outcome=outcome,
        details=details,
    )
