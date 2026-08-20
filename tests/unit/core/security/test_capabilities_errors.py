"""Sprint 30 (B): tests for src/backend/core/security/capabilities/errors.py.

This module defines capability-related exceptions used by the capability
gate (P0-S4). Coverage was 0% before Sprint 30.
"""
from __future__ import annotations

import pytest


class TestCapabilityDeniedError:
    """CapabilityDeniedError is raised when a plugin requests
    a capability it doesn't have."""

    def test_basic_construction(self) -> None:
        from src.backend.core.security.capabilities.errors import (
            CapabilityDeniedError,
        )

        err = CapabilityDeniedError(
            plugin="my_plugin",
            capability="ai.chat",
            requested_scope="read:users",
            declared_scope="read:public",
            tenant="tenant_a",
            correlation_id="corr-123",
        )
        assert err.plugin == "my_plugin"
        assert err.capability == "ai.chat"
        assert err.requested_scope == "read:users"
        assert err.declared_scope == "read:public"
        assert err.tenant == "tenant_a"
        assert err.correlation_id == "corr-123"

    def test_message_format(self) -> None:
        from src.backend.core.security.capabilities.errors import (
            CapabilityDeniedError,
        )

        err = CapabilityDeniedError(
            plugin="my_plugin",
            capability="ai.chat",
            requested_scope="read:users",
            declared_scope=None,
            tenant="tenant_a",
            correlation_id="corr-123",
        )
        msg = str(err)
        assert "my_plugin" in msg
        assert "ai.chat" in msg

    def test_correlation_id_in_audit_payload(self) -> None:
        from src.backend.core.security.capabilities.errors import (
            CapabilityDeniedError,
        )

        err = CapabilityDeniedError(
            plugin="plugin",
            capability="cap",
            requested_scope="scope",
            declared_scope=None,
            tenant="t",
            correlation_id="my-corr-id-456",
        )
        # correlation_id should be stored for audit trail
        assert err.correlation_id == "my-corr-id-456"


class TestInheritance:
    """Errors should inherit from appropriate base classes."""

    def test_capability_denied_is_exception(self) -> None:
        from src.backend.core.security.capabilities.errors import (
            CapabilityDeniedError,
        )

        assert issubclass(CapabilityDeniedError, Exception)
        # Can be raised and caught
        with pytest.raises(CapabilityDeniedError):
            raise CapabilityDeniedError(
                plugin="x", capability="y", requested_scope="z",
                declared_scope=None, tenant="t", correlation_id="c",
            )
