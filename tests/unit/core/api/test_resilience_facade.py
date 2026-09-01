"""Unit-тесты ``core.api.resilience`` — coverage ratchet (S48 W17).

core/api/resilience.py — Sprint 38 R13 FIX facade: re-exports canonical
resilience primitives (CircuitBreaker, RateLimiter, Bulkhead,
unified_rate_limiter) после S44 W3 layer migration. 6 statements,
0% coverage.

Цель slice: 0% → 100% через __all__ audit + type/callable identity.
"""

from __future__ import annotations

import pytest

from src.backend.core.api import resilience
from src.backend.core.api.resilience import (
    Bulkhead,
    CircuitBreaker,
    RateLimiter,
    rate_limiter,
    unified_rate_limiter,
)


@pytest.mark.unit
class TestResilienceFacadeAllExports:
    """``__all__`` audit + type/callable identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["rate_limiter", "unified_rate_limiter", "RateLimiter", "CircuitBreaker", "Bulkhead"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(resilience, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in resilience.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 5 символов."""
        assert len(resilience.__all__) == 5

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает Sprint 38 R13 FIX."""
        assert resilience.__doc__ is not None
        assert "Sprint 38" in resilience.__doc__


@pytest.mark.unit
class TestResilienceFacadeIdentity:
    """Identity checks для R13 FIX re-exports."""

    def test_rate_limiter_aliases_unified_rate_limiter(self) -> None:
        """``rate_limiter`` = ``unified_rate_limiter`` (backward-compat alias)."""
        # Pre-R13 code expected ``rate_limiter`` symbol; R13 сохранил
        # backward compat через alias на unified_rate_limiter module.
        assert rate_limiter is unified_rate_limiter

    def test_circuit_breaker_is_class(self) -> None:
        """``CircuitBreaker`` — type (class)."""
        assert isinstance(CircuitBreaker, type)

    def test_rate_limiter_protocol(self) -> None:
        """``RateLimiter`` — Protocol class."""
        from typing import Protocol

        # Может быть Protocol или ABC. Проверяем только что callable type.
        assert isinstance(RateLimiter, type)

    def test_bulkhead_is_class(self) -> None:
        """``Bulkhead`` — type (class)."""
        assert isinstance(Bulkhead, type)
