"""Unit-тесты ``infrastructure.policy`` — coverage ratchet (S49 W9).

infrastructure/policy/__init__.py — ADR-012 OPA + Casbin two-layer auth facade:
re-exports CasbinAdapter (RBAC), OPAClient (data-level policy), PolicyDecision.
11 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure import policy
from src.backend.infrastructure.policy import (
    CasbinAdapter,
    OPAClient,
    PolicyDecision,
)


@pytest.mark.unit
class TestPolicyFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["CasbinAdapter", "OPAClient", "PolicyDecision"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(policy, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in policy.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 3 символа."""
        assert len(policy.__all__) == 3

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает ADR-012 OPA + Casbin."""
        assert policy.__doc__ is not None
        assert "ADR-012" in policy.__doc__ or "OPA" in policy.__doc__


@pytest.mark.unit
class TestPolicyFacadeIdentity:
    """Identity checks для re-exports."""

    def test_casbin_adapter_is_class(self) -> None:
        """``CasbinAdapter`` — class (RBAC adapter)."""
        assert isinstance(CasbinAdapter, type)

    def test_opa_client_is_class(self) -> None:
        """``OPAClient`` — class (OPA Rego policy client)."""
        assert isinstance(OPAClient, type)

    def test_policy_decision_is_class(self) -> None:
        """``PolicyDecision`` — class (decision result dataclass / enum)."""
        assert isinstance(PolicyDecision, type)
