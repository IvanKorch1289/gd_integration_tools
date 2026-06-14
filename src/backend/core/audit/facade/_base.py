"""S107 W3 — ``core.audit.facade._base``: canonical audit emit + safe wrapper.

Per-domain helpers (S106 W2 Path A) живут в отдельных модулях пакета
``core.audit.facade``: ``authorization``, ``waf``, ``capability``,
``secrets``, ``ai``, ``banking``. Все они делегируют на
``emit_audit`` (здесь).

References:
* ADR-0187 (S103 closure)
* ``docs/migration/audit-emit-deprecation.md`` (Path A/B/C/D guide)
* ``tools/check_audit_deprecation.py`` (S105 W2 regression guard)
"""

from __future__ import annotations

from typing import Any

from src.backend.core.audit.facade.audit_service import get_unified_audit_service

__all__ = ("emit_audit", "emit_audit_safe")


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


def emit_audit_safe(
    *,
    event: str,
    action: str = "",
    outcome: str = "success",
    details: dict[str, Any] | None = None,
    severity: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Any:
    """Emit audit event ``_safe`` variant (Path A pattern E/G — never raises).

    Used by ``core/security/pii_tokenizer.py`` (3 calls) и
    ``dsl/engine/processors/agent_dsl/_base.py`` (3 calls).
    Wraps ``emit_audit`` в try/except — PII / agent pipelines не должны
    raise при audit failures.

    Args:
        event: Event name.
        action: Action performed.
        outcome: ``"success"`` / ``"failure"``.
        details: Optional details dict.
        severity: Optional severity (``"info"`` / ``"warning"`` / ``"error"``).
        extra: Optional extra fields (merged into details).

    Returns:
        None (always, even on emit failure) или coroutine.
    """
    merged_details: dict[str, Any] = dict(details or {})
    if severity is not None:
        merged_details["severity"] = severity
    if extra:
        merged_details.update(extra)
    try:
        return emit_audit(
            event=event,
            actor="system",
            action=action,
            outcome=outcome,
            details=merged_details or None,
        )
    except Exception:  # noqa: BLE001 — _safe variant per design
        return None
