"""Unit-тесты ``infrastructure.observability`` — coverage ratchet (Post-Plan A Sprint 9).

core/infrastructure/observability (G3) facade: re-exports 4 symbols
(get_correlation_id, new_correlation_id, set_correlation_context,
redact_for_observability). ~8 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + callable identity.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure import observability
from src.backend.infrastructure.observability import (
    get_correlation_id,
    new_correlation_id,
    redact_for_observability,
    set_correlation_context,
)


@pytest.mark.unit
class TestObservabilityFacadeAllExports:
    """``__all__`` audit + callable identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "get_correlation_id",
            "new_correlation_id",
            "set_correlation_context",
            "redact_for_observability",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(observability, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in observability.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 4 символа."""
        assert len(observability.__all__) == 4

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает observability (G3)."""
        assert observability.__doc__ is not None
        assert "Observability" in observability.__doc__ or "G3" in observability.__doc__


@pytest.mark.unit
class TestObservabilityFacadeIdentity:
    """Identity checks для 4 callables."""

    def test_get_correlation_id_is_callable(self) -> None:
        """``get_correlation_id`` — callable."""
        assert callable(get_correlation_id)

    def test_new_correlation_id_is_callable(self) -> None:
        """``new_correlation_id`` — callable."""
        assert callable(new_correlation_id)

    def test_set_correlation_context_is_callable(self) -> None:
        """``set_correlation_context`` — callable (contextvars wrapper)."""
        assert callable(set_correlation_context)

    def test_redact_for_observability_is_callable(self) -> None:
        """``redact_for_observability`` — callable (PII filter)."""
        assert callable(redact_for_observability)
