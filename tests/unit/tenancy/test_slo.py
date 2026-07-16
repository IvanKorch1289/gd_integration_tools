"""S178 #4: тесты per-tenant SLO модуля.

Проверяет:
- TenantSLO.default() — production baseline values
- TenantSLO.for_tenant() — backward-compat (всегда default в S178)
- evaluate() — все 3 метрики (latency, availability, error_rate)
- within_slo — aggregate verdict
- to_log_dict() — structured log format
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.tenancy import SLOEvaluation, TenantSLO


class TestTenantSLODefault:
    """S178 #4: production baseline SLO."""

    def test_default_values(self) -> None:
        """Default = 500ms p99, 99.9% availability, 1% error rate."""
        slo = TenantSLO.default()
        assert slo.latency_p99_ms == 500.0
        assert slo.availability_target == 0.999
        assert slo.error_rate_target == 0.01

    def test_default_is_frozen(self) -> None:
        """Frozen dataclass — нельзя mutate fields."""
        slo = TenantSLO.default()
        with pytest.raises((AttributeError, TypeError)):
            slo.latency_p99_ms = 1000.0  # type: ignore[misc]

    def test_custom_values(self) -> None:
        """Custom constructor принимает произвольные значения."""
        slo = TenantSLO(
            latency_p99_ms=200.0,
            availability_target=0.9999,
            error_rate_target=0.001,
        )
        assert slo.latency_p99_ms == 200.0
        assert slo.availability_target == 0.9999
        assert slo.error_rate_target == 0.001


class TestTenantSLOForTenant:
    """S178 #4: TenantSLO.for_tenant() — backward-compat."""

    def test_for_tenant_with_id_returns_default(self) -> None:
        """S178 #4: per-tenant override не реализован → всегда default."""
        slo = TenantSLO.for_tenant("tenant-42")
        assert slo == TenantSLO.default()

    def test_for_tenant_with_none_returns_default(self) -> None:
        """``for_tenant(None)`` — default."""
        slo = TenantSLO.for_tenant(None)
        assert slo == TenantSLO.default()

    def test_for_tenant_does_not_crash_on_empty_string(self) -> None:
        """Empty string tenant_id → default (no exception)."""
        slo = TenantSLO.for_tenant("")
        assert slo == TenantSLO.default()


class TestEvaluateAllMetrics:
    """S178 #4: evaluate() все 3 метрики одновременно."""

    def test_all_within_slo(self) -> None:
        """Все метрики within budget → within_slo=True."""
        slo = TenantSLO.default()
        eval_ = slo.evaluate(
            latency_p99_ms=200.0,
            availability=0.9995,
            error_rate=0.005,
        )
        assert eval_.within_slo is True
        assert eval_.latency_ok is True
        assert eval_.availability_ok is True
        assert eval_.error_rate_ok is True

    def test_latency_violation(self) -> None:
        """latency > budget → within_slo=False."""
        slo = TenantSLO.default()
        eval_ = slo.evaluate(
            latency_p99_ms=600.0,
            availability=0.9995,
            error_rate=0.005,
        )
        assert eval_.within_slo is False
        assert eval_.latency_ok is False
        assert eval_.availability_ok is True
        assert eval_.error_rate_ok is True

    def test_availability_violation(self) -> None:
        """availability < target → within_slo=False."""
        slo = TenantSLO.default()
        eval_ = slo.evaluate(
            latency_p99_ms=200.0,
            availability=0.99,  # < 0.999
            error_rate=0.005,
        )
        assert eval_.within_slo is False
        assert eval_.latency_ok is True
        assert eval_.availability_ok is False
        assert eval_.error_rate_ok is True

    def test_error_rate_violation(self) -> None:
        """error_rate > target → within_slo=False."""
        slo = TenantSLO.default()
        eval_ = slo.evaluate(
            latency_p99_ms=200.0,
            availability=0.9995,
            error_rate=0.05,  # > 0.01
        )
        assert eval_.within_slo is False
        assert eval_.latency_ok is True
        assert eval_.availability_ok is True
        assert eval_.error_rate_ok is False


class TestEvaluatePartial:
    """S178 #4: evaluate() с partial metrics (None = не замеряли)."""

    def test_no_metrics_returns_true(self) -> None:
        """Нет метрик → within_slo=True (vacuously)."""
        slo = TenantSLO.default()
        eval_ = slo.evaluate()
        assert eval_.within_slo is True

    def test_only_latency(self) -> None:
        """Только latency — другие = None."""
        slo = TenantSLO.default()
        eval_ = slo.evaluate(latency_p99_ms=200.0)
        assert eval_.latency_ok is True
        assert eval_.availability_ok is None
        assert eval_.error_rate_ok is None
        assert eval_.within_slo is True

    def test_only_latency_violation_marks_out_of_slo(self) -> None:
        """latency violation alone → within_slo=False."""
        slo = TenantSLO.default()
        eval_ = slo.evaluate(latency_p99_ms=9999.0)
        assert eval_.within_slo is False


class TestToLogDict:
    """S178 #4: structured log integration."""

    def test_to_log_dict_keys(self) -> None:
        """Все slo.* keys присутствуют."""
        slo = TenantSLO.default()
        eval_ = slo.evaluate(
            latency_p99_ms=200.0,
            availability=0.9995,
            error_rate=0.005,
        )
        log_dict = eval_.to_log_dict()
        expected_keys = {
            "slo.latency_p99_ms",
            "slo.latency_ok",
            "slo.availability",
            "slo.availability_ok",
            "slo.error_rate",
            "slo.error_rate_ok",
            "slo.within_slo",
            "slo.target_latency_p99_ms",
            "slo.target_availability",
            "slo.target_error_rate",
        }
        assert set(log_dict.keys()) == expected_keys

    def test_to_log_dict_includes_targets(self) -> None:
        """Target values присутствуют (для debugging)."""
        slo = TenantSLO.default()
        eval_ = slo.evaluate()
        log_dict = eval_.to_log_dict()
        assert log_dict["slo.target_latency_p99_ms"] == 500.0
        assert log_dict["slo.target_availability"] == 0.999
        assert log_dict["slo.target_error_rate"] == 0.01

    def test_to_log_dict_partial_keeps_none(self) -> None:
        """None значения остаются в dict (для observability)."""
        slo = TenantSLO.default()
        eval_ = slo.evaluate(latency_p99_ms=200.0)
        log_dict = eval_.to_log_dict()
        assert log_dict["slo.latency_p99_ms"] == 200.0
        assert log_dict["slo.availability"] is None
        assert log_dict["slo.availability_ok"] is None
        assert log_dict["slo.error_rate"] is None
        assert log_dict["slo.error_rate_ok"] is None


class TestSLOEvaluationImport:
    """S178 #4: re-export из src.backend.core.tenancy."""

    def test_slo_evaluation_importable_from_tenancy(self) -> None:
        """``from src.backend.core.tenancy import SLOEvaluation, TenantSLO``."""
        from src.backend.core.tenancy import SLOEvaluation, TenantSLO

        assert SLOEvaluation is not None
        assert TenantSLO is not None

    def test_tenancy_all_exports(self) -> None:
        """``tenancy.__all__`` содержит новые exports."""
        import src.backend.core.tenancy as tenancy_mod

        assert "TenantSLO" in tenancy_mod.__all__
        assert "SLOEvaluation" in tenancy_mod.__all__