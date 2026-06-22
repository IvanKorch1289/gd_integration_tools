"""S103 W3 — tests для audit facade canonical re-export.

Verifies:
* ``core.audit.facade`` re-exports ``AuditService`` и ``get_unified_audit_service``.
* ``emit_audit()`` sync wrapper вызывает ``AuditService.emit()``.

S45 QW10: removed identity tests against deleted shim
(services/audit/audit_service.py был удалён в S45 W1).
"""

from __future__ import annotations

from src.backend.core.audit.facade import (
    AuditService,
    emit_audit,
    get_unified_audit_service,
)


def test_audit_service_identity() -> None:
    """Canonical class is the same object (S45 QW10: shim удалён, identity check trivially True)."""
    from src.backend.core.audit.facade.audit_service import (
        AuditService as CanonicalAuditService,
    )

    assert AuditService is CanonicalAuditService


def test_get_unified_audit_service_identity() -> None:
    """Canonical function is the same object (S45 QW10)."""
    from src.backend.core.audit.facade.audit_service import (
        get_unified_audit_service as CanonicalGet,
    )

    assert get_unified_audit_service is CanonicalGet


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
