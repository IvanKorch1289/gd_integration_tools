"""S114 W2 — regression test для AuditService shim (3 import paths = same class).

S113 W1 перенёс AuditService из services/audit/ в core/audit/facade/.
Backward-compat shim в services/audit/audit_service.py re-export'ит.
Этот test гарантирует, что shim остаётся синхронным с canonical location
при будущих refactor'ах.
"""

from __future__ import annotations


def test_audit_service_three_paths_resolve_to_same_class() -> None:
    """All 3 import paths дают один и тот же класс object.

    Paths:
    - src.backend.core.audit.facade.audit_service (canonical, S113 W1)
    - src.backend.core.audit.facade (re-export, S107 W3)
    - src.backend.services.audit.audit_service (backward-compat shim, S113 W1)
    """
    from src.backend.core.audit.facade import AuditService as FacadeAuditService
    from src.backend.core.audit.facade.audit_service import (
        AuditService as CanonicalAuditService,
    )
    from src.backend.services.audit.audit_service import (
        AuditService as ShimAuditService,
    )

    assert CanonicalAuditService is FacadeAuditService
    assert CanonicalAuditService is ShimAuditService
    assert ShimAuditService is FacadeAuditService


def test_get_unified_audit_service_three_paths_resolve_to_same_function() -> None:
    """All 3 import paths дают одну и ту же функцию."""
    from src.backend.core.audit.facade import get_unified_audit_service as FacadeGet
    from src.backend.core.audit.facade.audit_service import (
        get_unified_audit_service as CanonicalGet,
    )
    from src.backend.services.audit.audit_service import (
        get_unified_audit_service as ShimGet,
    )

    assert CanonicalGet is FacadeGet
    assert CanonicalGet is ShimGet


def test_audit_service_singleton_via_shim() -> None:
    """get_unified_audit_service через shim возвращает тот же singleton."""
    from src.backend.services.audit.audit_service import get_unified_audit_service

    svc1 = get_unified_audit_service()
    svc2 = get_unified_audit_service()
    assert svc1 is svc2
    assert svc1.__class__.__name__ == "AuditService"
    # Canonical location check (defensive against future move).
    assert svc1.__class__.__module__ == "src.backend.core.audit.facade.audit_service"
