"""S107 W3 — ``core.audit.facade.secrets``: secret rotation/access audit.

Per-domain helper (S106 W2 Path A pattern C — typed Pydantic).
Used by ``core/security/secret_rotation.py`` (rotation) and
``core/security/credential_provider.py`` (access).

NB: эти функции emit'ят audit-event для **метаданных** обращения
(actor, resource, outcome). Содержимое секрета НИКОГДА не
включается в payload.
"""

from __future__ import annotations

from typing import Any, Literal

from src.backend.core.audit.facade._base import emit_audit

__all__ = ("emit_secret_access", "emit_secret_rotation")


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
        Result of ``AuditService.emit()`` (coroutine — caller awaits).

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


async def emit_secret_access(
    *,
    credential_name: str,
    secret_ref: str,
    actor: str,
    outcome: Literal["success", "failure"],
    cache_status: Literal["hit", "miss"],
    resolution_id: str | None = None,
    error_class: str | None = None,
) -> None:
    """Emit audit event for credential access (Cycle 60 L8).

    Cycle 59 review revealed that ``CredentialProvider`` claimed
    "Audit-emit события при каждом обращении" в module docstring, но
    emit'ил только ``_logger.info``. This helper makes the claim true.

    NB: секретное содержимое НИКОГДА не передаётся — только метаданные
    обращения (имя, ref, actor, cache_status, outcome).

    Args:
        credential_name: Имя credential spec.
        secret_ref: Vault path или env var (``vault:...`` / ``env:...``).
        actor: Кто запросил credential (principal / system).
        outcome: ``"success"`` / ``"failure"``.
        cache_status: ``"hit"`` (cache hit) / ``"miss"`` (resolved fresh).
        resolution_id: Уникальный ID резолва (только на success).
        error_class: Имя исключения при failure.

    """
    details: dict[str, Any] = {
        "credential_name": credential_name,
        "cache_status": cache_status,
    }
    if resolution_id is not None:
        details["resolution_id"] = resolution_id
    if error_class is not None:
        details["error_class"] = error_class
    try:
        await emit_audit(
            event="secret.access",
            actor=actor,
            resource=secret_ref,
            action="resolve",
            outcome=outcome,
            details=details,
        )
    except (ImportError, AttributeError, RuntimeError) as audit_exc:
        # cycle-9/D-AUDIT-1033: narrow exceptions + observability.
        # ImportError — audit facade missing, AttributeError — API
        # change, RuntimeError — backend unavailable.
        import logging  # noqa: F401 — availability probe
        logging.getLogger(__name__).debug(
            "secrets_audit.emit_failed",
            extra={"error": str(audit_exc)},
        )
