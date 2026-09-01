"""Unit-тесты ``core.services`` — coverage ratchet (S48 W24).

core/services/__init__.py — Sprint 225 lazy proxy: ``__getattr__``-based
forwarding к ``services.core.base_external_api.BaseExternalAPIClient`` для
устранения core → services layer-violation. 1 statement + lazy __getattr__,
0% coverage.

Цель slice: 0% → 100% через __all__ audit + __getattr__ lazy resolution +
AttributeError на unknown name.
"""

from __future__ import annotations

import pytest

from src.backend.core import services


@pytest.mark.unit
class TestServicesProxy:
    """``__getattr__`` lazy proxy → services.core.base_external_api."""

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 1 symbol (BaseExternalAPIClient)."""
        assert len(services.__all__) == 1
        assert "BaseExternalAPIClient" in services.__all__

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает Sprint 225 lazy proxy."""
        assert services.__doc__ is not None
        assert "Sprint 225" in services.__doc__ or "lazy" in services.__doc__.lower()

    def test_getattr_resolves_base_external_api_client(self) -> None:
        """``services.BaseExternalAPIClient`` → lazy resolves to actual class."""
        cls = services.BaseExternalAPIClient
        assert isinstance(cls, type)
        # Should be the actual BaseExternalAPIClient from services.core.
        from src.backend.services.core.base_external_api import (
            BaseExternalAPIClient as Canonical,
        )

        assert cls is Canonical

    def test_getattr_unknown_raises_attribute_error(self) -> None:
        """``__getattr__`` для unknown name → AttributeError (не ImportError)."""
        with pytest.raises(AttributeError, match="has no attribute"):
            _ = services.NonExistentSymbol  # type: ignore[attr-defined]

    def test_module_has_getattr(self) -> None:
        """``services.__getattr__`` — определён на module level."""
        assert hasattr(services, "__getattr__")
        assert callable(services.__getattr__)
