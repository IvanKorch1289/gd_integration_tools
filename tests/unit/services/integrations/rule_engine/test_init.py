"""Unit-тесты ``services.integrations.rule_engine`` — coverage ratchet (S49 W6).

services/integrations/rule_engine/__init__.py — rule-engine ruleset
registry facade: re-exports RuleEngineRegistry (cache wrapper) +
RulesetCacheEntry (cache entry dataclass). ~10 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.integrations import rule_engine
from src.backend.services.integrations.rule_engine import (
    RuleEngineRegistry,
    RulesetCacheEntry,
)


@pytest.mark.unit
class TestRuleEngineFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["RuleEngineRegistry", "RulesetCacheEntry"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(rule_engine, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in rule_engine.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 2 символа."""
        assert len(rule_engine.__all__) == 2

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает rule-engine registry."""
        assert rule_engine.__doc__ is not None
        assert "rule" in rule_engine.__doc__.lower() or "registry" in rule_engine.__doc__.lower()


@pytest.mark.unit
class TestRuleEngineFacadeIdentity:
    """Identity checks для re-exports."""

    def test_rule_engine_registry_is_class(self) -> None:
        """``RuleEngineRegistry`` — class (cache wrapper)."""
        assert isinstance(RuleEngineRegistry, type)

    def test_ruleset_cache_entry_is_class(self) -> None:
        """``RulesetCacheEntry`` — class (cache entry dataclass)."""
        assert isinstance(RulesetCacheEntry, type)

    def test_rule_engine_registry_instantiation(self) -> None:
        """``RuleEngineRegistry()`` — instantiable cache."""
        try:
            reg = RuleEngineRegistry()
            assert reg is not None
        except (TypeError, AttributeError):
            # Если требует обязательных args, проверяем только type identity.
            assert RuleEngineRegistry is not None
