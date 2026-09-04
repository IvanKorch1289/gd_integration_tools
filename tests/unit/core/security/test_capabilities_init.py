"""Tests for core/security/capabilities/__init__.py (S99 — coverage push).

Module-level re-exports — verifies all expected names are accessible.
"""

from __future__ import annotations


def test_capabilities_dunder_all_count() -> None:
    """__all__ содержит 27 публичных symbols."""
    import src.backend.core.security.capabilities as mod

    assert len(mod.__all__) == 27


def test_capabilities_dunder_all_specific_names() -> None:
    """__all__ содержит ключевые классы и функции."""
    import src.backend.core.security.capabilities as mod

    expected = (
        "CAPABILITY_NAME_PATTERN",
        "DEFAULT_CAPABILITY_CATALOG",
        "SYSTEM_TENANT_ID",
        "AuditCallback",
        "CapabilityAuditEvent",
        "CapabilityAuditEventKind",
        "CapabilityDef",
        "CapabilityDeniedError",
        "CapabilityError",
        "CapabilityGate",
        "CapabilityNotFoundError",
        "CapabilityPolicy",
        "CapabilityRef",
        "CapabilityRule",
        "CapabilitySupersetError",
        "CapabilityTenant",
        "CapabilityVocabulary",
        "ExactAliasMatcher",
        "GlobScopeMatcher",
        "PolicyDecision",
        "ScopeMatcher",
        "SegmentedGlobMatcher",
        "TenantContext",
        "URISchemeMatcher",
        "build_default_vocabulary",
        "check_capabilities_subset",
        "log_capability_event",
    )
    assert mod.__all__ == expected


def test_capability_gate_importable() -> None:
    """CapabilityGate импортируется через public API."""
    from src.backend.core.security.capabilities import CapabilityGate

    assert CapabilityGate is not None


def test_capability_ref_importable() -> None:
    """CapabilityRef импортируется через public API."""
    from src.backend.core.security.capabilities import CapabilityRef

    assert CapabilityRef is not None


def test_capability_denied_error_importable() -> None:
    """CapabilityDeniedError импортируется через public API."""
    from src.backend.core.security.capabilities import CapabilityDeniedError

    assert issubclass(CapabilityDeniedError, Exception)


def test_tenant_context_importable() -> None:
    """TenantContext импортируется через public API."""
    from src.backend.core.security.capabilities import TenantContext

    assert TenantContext is not None


def test_build_default_vocabulary_importable() -> None:
    """build_default_vocabulary function импортируется."""
    from src.backend.core.security.capabilities import build_default_vocabulary

    assert callable(build_default_vocabulary)
