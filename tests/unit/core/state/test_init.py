"""Unit-тесты ``core.state`` — coverage ratchet (S48 W22).

core/state/__init__.py — facade для runtime-состояния приложения:
``blocked_routes`` и ``disabled_feature_flags`` мутабельные dict'ы,
разделяемые между слоями. 3 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + dict type identity.
"""

from __future__ import annotations

import pytest

from src.backend.core import state
from src.backend.core.state import blocked_routes, disabled_feature_flags


@pytest.mark.unit
class TestStateFacadeAllExports:
    """``__all__`` audit + identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["blocked_routes", "disabled_feature_flags"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(state, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in state.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 2 символа."""
        assert len(state.__all__) == 2

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает runtime-состояния."""
        assert state.__doc__ is not None
        assert "Runtime" in state.__doc__ or "состояния" in state.__doc__


@pytest.mark.unit
class TestStateFacadeRuntimeContainers:
    """Identity checks для runtime containers."""

    def test_blocked_routes_is_set(self) -> None:
        """``blocked_routes`` — set (mutable runtime container для route names)."""
        assert isinstance(blocked_routes, set)

    def test_disabled_feature_flags_is_set(self) -> None:
        """``disabled_feature_flags`` — set (mutable runtime container для flag names)."""
        assert isinstance(disabled_feature_flags, set)

    def test_blocked_routes_is_writable(self) -> None:
        """``blocked_routes`` writable (mutable state)."""
        blocked_routes.add("__test_route__")
        assert "__test_route__" in blocked_routes
        blocked_routes.discard("__test_route__")
