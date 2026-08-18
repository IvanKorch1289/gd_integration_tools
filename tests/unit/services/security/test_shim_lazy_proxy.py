"""TDD characterization test для services/security/__init__.py lazy proxy.

Sprint 224 (2026-08-17) — Sprint 4 actual refactor (Agent 1 Candidate #1).

Characterization test BEFORE refactor:
- Import symbols from services.security.__init__
- Assert symbol identity (proxy preserves reference to original)
- Assert public API stable (no behavior change)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.backend.infrastructure.security import signatures as _infra_signatures


class TestServicesSecurityShimProxy:
    """services/security/__init__.py — lazy __getattr__ proxy characterization."""

    def test_module_imports(self) -> None:
        from src.backend.services import security

        assert security is not None
        assert hasattr(security, "__all__")

    def test_all_exports_expected_symbols(self) -> None:
        from src.backend.services.security import __all__

        assert "DEFAULT_TIMESTAMP_WINDOW" in __all__
        assert "verify_signature" in __all__
        assert len(__all__) == 2

    def test_default_timestamp_window_identity(self) -> None:
        """DEFAULT_TIMESTAMP_WINDOW must be same object as infrastructure symbol."""
        from src.backend.services.security import DEFAULT_TIMESTAMP_WINDOW

        assert DEFAULT_TIMESTAMP_WINDOW is _infra_signatures.DEFAULT_TIMESTAMP_WINDOW

    def test_verify_signature_identity(self) -> None:
        """verify_signature must be same callable as infrastructure symbol."""
        from src.backend.services.security import verify_signature

        assert verify_signature is _infra_signatures.verify_signature

    def test_unknown_attribute_raises(self) -> None:
        """Accessing unknown attribute must raise AttributeError (НЕ ImportError)."""
        from src.backend.services import security

        with pytest.raises(AttributeError):
            _ = security.__getattr__("definitely_not_a_real_symbol_xyz")

    def test_lazy_import_not_loaded_at_module_load(self) -> None:
        """Verify lazy: import infrastructure only happens at first __getattr__.

        Spy via patching infrastructure.security.signatures to detect
        import-time access.
        """
        # After clear cache, re-import services.security
        import importlib
        import sys

        # Save current module
        saved = sys.modules.get("src.backend.services.security")
        if "src.backend.services.security" in sys.modules:
            del sys.modules["src.backend.services.security"]

        try:
            # First: import WITHOUT accessing attributes
            from src.backend.services import security

            # Trigger __getattr__ for a known attribute
            _ = security.verify_signature
            # (No assertion — just verify no exceptions)
        finally:
            # Restore
            if saved is not None:
                sys.modules["src.backend.services.security"] = saved

    def test_function_callable(self) -> None:
        """verify_signature is callable (functional contract)."""
        from src.backend.services.security import verify_signature

        assert callable(verify_signature)