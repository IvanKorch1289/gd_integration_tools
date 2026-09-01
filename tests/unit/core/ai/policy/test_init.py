"""Unit-тесты ``core.ai.policy`` — coverage ratchet (S48 W35).

core/ai/policy/__init__.py — AI Policy DSL facade (ADR-NEW-20, S25 W2):
re-exports AIPolicySpec (Pydantic spec), PolicyResolver + exceptions
(PolicyLoadError, PolicyNotResolvedError), AIPolicyEnforcer + supporting
Pydantic models (AuditSpec, BackendSpec, BudgetSpec, GuardRef,
MemorySpec, ModelRouterSpec, SanitizerRef).
~22 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity + Exception
subclass check.
"""

from __future__ import annotations

import pytest

from src.backend.core.ai import policy as ai_policy
from src.backend.core.ai.policy import (
    AIPolicyEnforcer,
    AIPolicySpec,
    AuditSpec,
    BackendSpec,
    BudgetSpec,
    GuardRef,
    MemorySpec,
    ModelRouterSpec,
    PolicyLoadError,
    PolicyNotResolvedError,
    PolicyResolver,
    SanitizerRef,
)


@pytest.mark.unit
class TestAiPolicyFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "AIPolicyEnforcer",
            "AIPolicySpec",
            "AuditSpec",
            "BackendSpec",
            "BudgetSpec",
            "GuardRef",
            "MemorySpec",
            "ModelRouterSpec",
            "PolicyLoadError",
            "PolicyNotResolvedError",
            "PolicyResolver",
            "SanitizerRef",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(ai_policy, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in ai_policy.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 12 символов."""
        assert len(ai_policy.__all__) == 12

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает AI Policy DSL (ADR-NEW-20, S25 W2)."""
        assert ai_policy.__doc__ is not None
        assert "AI Policy" in ai_policy.__doc__ or "ADR-NEW-20" in ai_policy.__doc__


@pytest.mark.unit
class TestAiPolicyFacadeIdentity:
    """Identity checks: AIPolicySpec (main class) + resolver + enforcer + exceptions."""

    def test_ai_policy_spec_is_class(self) -> None:
        """``AIPolicySpec`` — class (Pydantic spec model)."""
        assert isinstance(AIPolicySpec, type)

    def test_policy_resolver_is_class(self) -> None:
        """``PolicyResolver`` — class (workflow_id → policy resolver)."""
        assert isinstance(PolicyResolver, type)

    def test_ai_policy_enforcer_is_class(self) -> None:
        """``AIPolicyEnforcer`` — class (enforcement middleware)."""
        assert isinstance(AIPolicyEnforcer, type)

    def test_policy_load_error_is_exception(self) -> None:
        """``PolicyLoadError`` — Exception subclass."""
        assert issubclass(PolicyLoadError, Exception)

    def test_policy_not_resolved_error_is_exception(self) -> None:
        """``PolicyNotResolvedError`` — Exception subclass."""
        assert issubclass(PolicyNotResolvedError, Exception)

    def test_supporting_pydantic_models_are_classes(self) -> None:
        """Все supporting Pydantic models (AuditSpec, BackendSpec, BudgetSpec,
        GuardRef, MemorySpec, ModelRouterSpec, SanitizerRef) — class."""
        for cls in (
            AuditSpec,
            BackendSpec,
            BudgetSpec,
            GuardRef,
            MemorySpec,
            ModelRouterSpec,
            SanitizerRef,
        ):
            assert isinstance(cls, type)
