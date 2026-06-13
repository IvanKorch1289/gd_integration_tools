"""S107 W3 — ``core.audit.facade.secrets``: secret rotation audit.

Per-domain helper (S106 W2 Path A pattern C — typed Pydantic).
Used by ``core/security/secret_rotation.py`` (2 calls).
Translates ``RotationAuditEvent`` fields to canonical kwargs.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.audit.facade._base import emit_audit

__all__ = ("emit_secret_rotation",)


def emit_secret_rotation(
    *,
    secret_path: str,
    rotation_id: str,
    correlation_id: str,
    actor: str,
    outcome: str,
    error_class: str | None = None,
) -> Any:
    """Emit audit event for secret rotation (Path A pattern C — typed Pydantic).

    Used by ``core/security/secret_rotation.py`` (2 calls). Translates
    ``RotationAuditEvent`` fields to canonical kwargs.

    Args:
        secret_path: Secret path being rotated.
        rotation_id: Rotation identifier.
        correlation_id: Workflow correlation ID.
        actor: Who triggered rotation.
        outcome: ``"success"`` / ``"failure"``.
        error_class: Exception class name if failed.

    Returns:
        Result of ``AuditService.emit()``.
    """
    details: dict[str, Any] = {
        "secret_path": secret_path,
        "rotation_id": rotation_id,
        "correlation_id": correlation_id,
    }
    if error_class is not None:
        details["error_class"] = error_class
    return emit_audit(
        event="secret.rotation",
        actor=actor,
        resource=secret_path,
        action="rotate",
        outcome=outcome,
        details=details,
    )
