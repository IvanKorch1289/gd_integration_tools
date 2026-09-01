"""Unit-тесты ``infrastructure.import_gateway`` — coverage ratchet (S49 W10).

infrastructure/import_gateway/__init__.py — W24 import backends facade:
re-exports ``build_import_gateway`` (factory for Postman/OpenAPI/WSDL
backends). 10 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + callable identity.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure import import_gateway
from src.backend.infrastructure.import_gateway import build_import_gateway


@pytest.mark.unit
class TestImportGatewayFacadeAllExports:
    """``__all__`` audit + callable identity."""

    def test_all_exports_accessible(self) -> None:
        """``build_import_gateway`` доступен через facade."""
        assert hasattr(import_gateway, "build_import_gateway")
        assert "build_import_gateway" in import_gateway.__all__

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 1 symbol."""
        assert len(import_gateway.__all__) == 1

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает W24 import backends."""
        assert import_gateway.__doc__ is not None
        assert "W24" in import_gateway.__doc__ or "ImportGateway" in import_gateway.__doc__


@pytest.mark.unit
class TestImportGatewayFacadeIdentity:
    """Identity checks для re-exports."""

    def test_build_import_gateway_is_callable(self) -> None:
        """``build_import_gateway`` — callable (factory function)."""
        assert callable(build_import_gateway)
