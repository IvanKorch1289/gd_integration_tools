"""S103 W3 — Audit facade canonical location + S106 W2 per-domain helpers.

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

S106 W2 (Audit Path A) — per-domain helpers для 7 distinct legacy patterns
(subagent discovery, S105 W2 Task 2 report). Каждый helper транслирует
domain-specific args в canonical facade kwargs. Позволяет постепенную
миграцию callsites без breaking changes (helper = additive, не замена).

References:
- ADR-0187 (S103 closure)
- ``docs/migration/audit-emit-deprecation.md`` (Path A/B/C/D guide)
- ``/home/user/.hermes/agent_workspaces/task2_audit_migration_report.md``
  (subagent discovery: 77 callsites, 7 distinct patterns)
- ``tools/check_audit_deprecation.py`` (S105 W2 regression guard)
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
    "emit_audit",
    # Per-domain helpers (S106 W2 Path A)
    "emit_authorization_decision",
    "emit_waf_evaluation",
    "emit_capability_check",
    "emit_secret_rotation",
    "emit_ai_workspace",
    "emit_audit_safe",
    "emit_banking_audit",
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


# === S106 W2 — per-domain helpers (Path A) ===
#
# Каждый helper транслирует domain-specific args в canonical facade kwargs.
# Subagent S105 W2 обнаружил 7 distinct patterns в legacy `_emit_audit`
# callsites. Path A = additive facade extensions, постепенная миграция.
#
# Pattern (per subagent Task 2 report §2):
# - A. Sync DI-callback (5 файлов): workspace_manager, routes/loader,
#      outbound_http, authorization_gateway, activity_capability_guard
# - B. Capability kwargs (1 mixin, 12+ inherited callsites):
#      cap/gate/{audit,declaration,check}_mixin.py
# - C. Async + custom Pydantic event (1 file, 2 calls): secret_rotation
# - D. Async emit kwargs (1 file, 4 calls): token_registry
# - E. Async `_safe` variant (1 file, 3 calls): agent_dsl/_base.py
# - F. Module-level bank args (1 file, 3 calls × 3 files): ai_banking/_audit.py
# - G. Async `_safe` emit (1 file, 3 calls): pii_tokenizer.py


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
    callsites in ``check_mixin.py`` + ``declaration_mixin.py``.
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


def emit_ai_workspace(event: dict[str, object]) -> Any:
    """Emit audit event for AI workspace (Path A pattern A, dict-based).

    Used by ``core/ai/workspace_manager.py`` (2 calls). Accepts raw dict
    payload (matches legacy ``self._audit(payload)`` signature).

    Args:
        event: Event dict (e.g. ``{"event": "workspace.create", ...}``).
            Must contain ``"event"`` key for canonical event name.

    Returns:
        Result of ``AuditService.emit()``.
    """
    event_name = str(event.get("event", "ai_workspace.event"))
    details: dict[str, Any] = {
        k: v for k, v in event.items() if k not in ("event", "actor", "resource", "action", "outcome")
    }
    return emit_audit(
        event=event_name,
        actor=str(event.get("actor", "system")),
        resource=str(event.get("resource", "")),
        action=str(event.get("action", "")),
        outcome=str(event.get("outcome", "success")),
        details=details or None,
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
    details: dict[str, Any] = {
        "processor": processor,
        "params": params,
    }
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
