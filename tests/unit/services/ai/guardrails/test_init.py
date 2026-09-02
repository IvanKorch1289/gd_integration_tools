"""Unit-тесты ``services.ai.guardrails`` — coverage ratchet (Post-Plan A Sprint 23).

core/ai/guardrails service package facade (Sprint 11 K1 W2): re-exports
4 symbols (GuardrailsConfig + GuardrailsThresholds Pydantic models +
LakeraClient class + LakeraResult dataclass). ~5 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.

NOTE: LLM Guard и Rebuff удалены 2026-07-16 (upstream archived, см.
``research/agent-framework/REPORT.md`` F4.1, F4.2). Остаются Lakera + NeMo.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai import guardrails
from src.backend.services.ai.guardrails import (
    GuardrailsConfig,
    GuardrailsThresholds,
    LakeraClient,
    LakeraResult,
)


@pytest.mark.unit
class TestGuardrailsFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["GuardrailsConfig", "GuardrailsThresholds", "LakeraClient", "LakeraResult"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(guardrails, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in guardrails.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 4 символа."""
        assert len(guardrails.__all__) == 4

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает per-tenant guardrails clients."""
        assert guardrails.__doc__ is not None
        assert "guardrail" in guardrails.__doc__.lower() or "Lakera" in guardrails.__doc__


@pytest.mark.unit
class TestGuardrailsFacadeIdentity:
    """Identity checks для 4 re-exports."""

    def test_guardrails_config_is_class(self) -> None:
        """``GuardrailsConfig`` — class (Pydantic config model)."""
        assert isinstance(GuardrailsConfig, type)

    def test_guardrails_thresholds_is_class(self) -> None:
        """``GuardrailsThresholds`` — class (Pydantic thresholds model)."""
        assert isinstance(GuardrailsThresholds, type)

    def test_lakera_client_is_class(self) -> None:
        """``LakeraClient`` — class (Lakera Guard API client)."""
        assert isinstance(LakeraClient, type)

    def test_lakera_result_is_class(self) -> None:
        """``LakeraResult`` — class (result dataclass)."""
        assert isinstance(LakeraResult, type)
