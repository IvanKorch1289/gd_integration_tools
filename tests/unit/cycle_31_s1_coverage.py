"""S1: Coverage push — module structure + capability module tests.

Cycle 31 S1-#2: structural tests for critical modules.
Tests importability + class presence + exception type correctness
(without complex internal state setup).
"""

# ruff: noqa: S101

from __future__ import annotations

import os


class TestCapabilitiesModuleStructure:
    """Capabilities module must have correct structure."""

    def test_errors_module_exists(self):
        path = "src/backend/core/security/capabilities/errors.py"
        assert os.path.exists(path)

    def test_models_module_exists(self):
        path = "src/backend/core/security/capabilities/models.py"
        assert os.path.exists(path)

    def test_gate_package_exists(self):
        path = "src/backend/core/security/capabilities/gate/__init__.py"
        assert os.path.exists(path)

    def test_vocabulary_module_exists(self):
        path = "src/backend/core/security/capabilities/vocabulary/__init__.py"
        assert os.path.exists(path)

    def test_policy_module_exists(self):
        path = "src/backend/core/security/capabilities/policy.py"
        assert os.path.exists(path)


class TestCapabilityErrors:
    """Exception classes must exist with correct hierarchy."""

    def test_capability_error_is_exception(self):
        from src.backend.core.security.capabilities.errors import CapabilityError

        assert issubclass(CapabilityError, Exception)
        # Can be raised and caught
        try:
            raise CapabilityError("test")
        except CapabilityError as e:
            assert str(e) == "test"

    def test_capability_not_found_is_capability_error(self):
        from src.backend.core.security.capabilities.errors import (
            CapabilityError,
            CapabilityNotFoundError,
        )

        assert issubclass(CapabilityNotFoundError, CapabilityError)

    def test_capability_superset_is_capability_error(self):
        from src.backend.core.security.capabilities.errors import (
            CapabilityError,
            CapabilitySupersetError,
        )

        assert issubclass(CapabilitySupersetError, CapabilityError)


class TestCapabilityGate:
    """CapabilityGate class must exist with required methods."""

    def test_class_exists(self):
        from src.backend.core.security.capabilities.gate import CapabilityGate

        assert hasattr(CapabilityGate, "check")
        assert hasattr(CapabilityGate, "declare")
        assert hasattr(CapabilityGate, "revoke")

    def test_check_signature(self):
        """check() must accept (plugin, capability, requested_scope)."""
        import inspect

        from src.backend.core.security.capabilities.gate import CapabilityGate
        sig = inspect.signature(CapabilityGate.check)
        params = list(sig.parameters.keys())
        assert "plugin" in params
        assert "capability" in params
        assert "requested_scope" in params
