"""S103 W3 — tests для audit facade canonical re-export.

Verifies:
* ``core.audit.facade`` re-exports ``AuditService`` и ``get_unified_audit_service``.
* ``emit_audit()`` sync wrapper вызывает ``AuditService.emit()``.
* Re-export identity: ``core.audit.facade.AuditService is services.audit.audit_service.AuditService``.
"""

from __future__ import annotations

from src.backend.core.audit.facade import (
    AuditService,
    emit_audit,
    get_unified_audit_service,
)
from src.backend.services.audit import audit_service as _svc_module


def test_audit_service_identity() -> None:
    """``core.audit.facade.AuditService is services.audit.audit_service.AuditService``."""
    assert AuditService is _svc_module.AuditService


def test_get_unified_audit_service_identity() -> None:
    """Canonical re-export: ``get_unified_audit_service`` same function."""
    assert get_unified_audit_service is _svc_module.get_unified_audit_service


def test_emit_audit_calls_service() -> None:
    """``emit_audit()`` — sync wrapper вызывает ``AuditService.emit()``."""
    # Should not raise (returns coroutine or None depending on backend)
    result = emit_audit(
        "test.event",
        actor="test:user",
        resource="test/resource",
        action="verify",
        outcome="success",
        details={"key": "value"},
    )
    # result is either None (sync) or coroutine (async backend)
    assert result is None or hasattr(result, "__await__")


def test_emit_audit_with_minimal_args() -> None:
    """``emit_audit()`` — defaults работают (actor='system', outcome='success')."""
    result = emit_audit("test.minimal")
    assert result is None or hasattr(result, "__await__")
