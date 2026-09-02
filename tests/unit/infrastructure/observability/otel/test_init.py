"""Unit-тесты ``infrastructure.observability.otel`` — coverage ratchet (Post-Plan A Sprint 26).

core/infrastructure/observability/otel subpackage (Sprint 3 K2 W1 + Sprint 16 K2 W3):
re-exports 3 functions (configure_otel, setup_otel_metrics, shutdown_otel_metrics).
~6 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + callable identity.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.observability import otel
from src.backend.infrastructure.observability.otel import (
    configure_otel,
    setup_otel_metrics,
    shutdown_otel_metrics,
)


@pytest.mark.unit
class TestOtelFacadeAllExports:
    """``__all__`` audit + callable identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["configure_otel", "setup_otel_metrics", "shutdown_otel_metrics"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(otel, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in otel.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 3 символа."""
        assert len(otel.__all__) == 3

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает OpenTelemetry baseline."""
        assert otel.__doc__ is not None
        assert "OpenTelemetry" in otel.__doc__ or "OTel" in otel.__doc__ or "otel" in otel.__doc__.lower()


@pytest.mark.unit
class TestOtelFacadeIdentity:
    """Identity checks для 3 callables."""

    def test_configure_otel_is_callable(self) -> None:
        """``configure_otel`` — callable (startup TracerProvider config)."""
        assert callable(configure_otel)

    def test_setup_otel_metrics_is_callable(self) -> None:
        """``setup_otel_metrics`` — callable (startup MeterProvider config)."""
        assert callable(setup_otel_metrics)

    def test_shutdown_otel_metrics_is_callable(self) -> None:
        """``shutdown_otel_metrics`` — callable (lifespan teardown)."""
        assert callable(shutdown_otel_metrics)
