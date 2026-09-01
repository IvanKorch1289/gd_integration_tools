"""Unit-тесты ``services.admin`` — coverage ratchet (S49 W7).

services/admin/__init__.py — Sprint 19 K5 W5b admin API facade: re-exports
AdminService + emit_admin_action (audit helper) + register_admin (sqladmin
setup function). 8 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class/function identity.
"""

from __future__ import annotations

import pytest

from src.backend.services import admin
from src.backend.services.admin import AdminService, emit_admin_action, register_admin


@pytest.mark.unit
class TestAdminFacadeAllExports:
    """``__all__`` audit + class/function identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["AdminService", "emit_admin_action", "register_admin"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(admin, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in admin.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 3 символа."""
        assert len(admin.__all__) == 3

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает Sprint 19 K5 W5b admin API."""
        assert admin.__doc__ is not None
        assert "Admin" in admin.__doc__ or "Sprint 19" in admin.__doc__


@pytest.mark.unit
class TestAdminFacadeIdentity:
    """Identity checks для re-exports."""

    def test_admin_service_is_class(self) -> None:
        """``AdminService`` — class (admin API service)."""
        assert isinstance(AdminService, type)

    def test_emit_admin_action_is_callable(self) -> None:
        """``emit_admin_action`` — callable (audit emit helper)."""
        assert callable(emit_admin_action)

    def test_register_admin_is_callable(self) -> None:
        """``register_admin`` — callable (sqladmin setup function)."""
        assert callable(register_admin)
