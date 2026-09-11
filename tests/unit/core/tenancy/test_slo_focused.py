"""Focused tests for ``TenantSLO`` (Sprint 24 coverage ratchet).

Цель: поднять покрытие ``src/backend/core/tenancy/slo.py`` с ~53% до ≥95%
путём детального покрытия TenantSLO + SLOEvaluation pure-evaluator.

Контракт API:
- ``TenantSLO(latency_p99_ms=500.0, availability_target=0.999, error_rate_target=0.01)`` — defaults.
- ``TenantSLO.default()`` — production baseline (все defaults).
- ``TenantSLO.for_tenant(tenant_id)`` — per-tenant override (S179+).
- ``slo.evaluate(*, latency_p99_ms, availability, error_rate)`` → SLOEvaluation.
- ``SLOEvaluation.to_log_dict()`` — structured log flat keys.
"""

from __future__ import annotations

import pytest

from src.backend.core.tenancy.slo import SLOEvaluation, TenantSLO


class TestTenantSLODefaults:
    """``TenantSLO()`` defaults + dataclass behavior."""

    def test_default_values(self) -> None:
        """Default SLO = production baseline."""
        slo = TenantSLO()
        assert slo.latency_p99_ms == 500.0
        assert slo.availability_target == 0.999
        assert slo.error_rate_target == 0.01

    def test_custom_values(self) -> None:
        """Кастомные пороги сохраняются."""
        slo = TenantSLO(
            latency_p99_ms=200.0,
            availability_target=0.9999,
            error_rate_target=0.001,
        )
        assert slo.latency_p99_ms == 200.0
        assert slo.availability_target == 0.9999
        assert slo.error_rate_target == 0.001

    def test_frozen_dataclass(self) -> None:
        """``TenantSLO`` frozen — нельзя mutate."""
        slo = TenantSLO()
        with pytest.raises((AttributeError, Exception)):  # FrozenInstanceError
            slo.latency_p99_ms = 100.0  # type: ignore[misc]

    def test_slots(self) -> None:
        """``TenantSLO`` — slots-based (нет __dict__)."""
        slo = TenantSLO()
        # slots classes don't have __dict__ on instances.
        assert not hasattr(slo, "__dict__") or slo.__slots__ == ("latency_p99_ms", "availability_target", "error_rate_target")


class TestTenantSLOFactoryMethods:
    """``default()`` и ``for_tenant()`` factory methods."""

    def test_default_classmethod(self) -> None:
        """``TenantSLO.default()`` возвращает SLO с defaults."""
        slo = TenantSLO.default()
        assert slo.latency_p99_ms == 500.0
        assert slo.availability_target == 0.999
        assert slo.error_rate_target == 0.01

    def test_default_returns_new_instance(self) -> None:
        """``default()`` возвращает новый instance каждый раз."""
        s1 = TenantSLO.default()
        s2 = TenantSLO.default()
        assert s1 is not s2
        assert s1 == s2  # Но values одинаковые.

    def test_for_tenant_none_returns_default(self) -> None:
        """``for_tenant(None)`` → default SLO."""
        slo = TenantSLO.for_tenant(None)
        assert slo == TenantSLO.default()

    def test_for_tenant_with_id_returns_default(self) -> None:
        """``for_tenant('tenant-1')`` → default SLO (S179+ overrides)."""
        slo = TenantSLO.for_tenant("tenant-1")
        assert slo.latency_p99_ms == 500.0
        assert slo.availability_target == 0.999

    def test_for_tenant_empty_string(self) -> None:
        """``for_tenant('')`` → default SLO."""
        slo = TenantSLO.for_tenant("")
        assert slo == TenantSLO.default()

    def test_for_tenant_with_unicode_id(self) -> None:
        """``for_tenant('тенант-🔧')`` → default SLO (любой non-None ID)."""
        slo = TenantSLO.for_tenant("тенант-🔧")
        assert slo == TenantSLO.default()


class TestTenantSLOEvaluate:
    """``TenantSLO.evaluate()`` — pure-evaluator без I/O."""

    def test_evaluate_no_metrics_within_slo(self) -> None:
        """Без метрик → ``within_slo=True`` (vacuously)."""
        slo = TenantSLO()
        result = slo.evaluate()
        assert result.within_slo is True
        assert result.latency_ok is None
        assert result.availability_ok is None
        assert result.error_rate_ok is None

    def test_evaluate_latency_within_budget(self) -> None:
        """``latency_p99_ms=200 < 500`` → ``latency_ok=True``."""
        slo = TenantSLO()
        result = slo.evaluate(latency_p99_ms=200.0)
        assert result.latency_ok is True
        assert result.within_slo is True
        assert result.latency_p99_ms == 200.0

    def test_evaluate_latency_exceeds_budget(self) -> None:
        """``latency_p99_ms=600 > 500`` → ``latency_ok=False``."""
        slo = TenantSLO()
        result = slo.evaluate(latency_p99_ms=600.0)
        assert result.latency_ok is False
        assert result.within_slo is False

    def test_evaluate_latency_at_boundary(self) -> None:
        """``latency_p99_ms=500 == 500`` → ``latency_ok=True`` (<=)."""
        slo = TenantSLO()
        result = slo.evaluate(latency_p99_ms=500.0)
        assert result.latency_ok is True

    def test_evaluate_availability_meets_target(self) -> None:
        """``availability=0.9995 >= 0.999`` → ``availability_ok=True``."""
        slo = TenantSLO()
        result = slo.evaluate(availability=0.9995)
        assert result.availability_ok is True
        assert result.within_slo is True

    def test_evaluate_availability_below_target(self) -> None:
        """``availability=0.99 < 0.999`` → ``availability_ok=False``."""
        slo = TenantSLO()
        result = slo.evaluate(availability=0.99)
        assert result.availability_ok is False
        assert result.within_slo is False

    def test_evaluate_availability_at_boundary(self) -> None:
        """``availability=0.999 == 0.999`` → ``availability_ok=True`` (>=)."""
        slo = TenantSLO()
        result = slo.evaluate(availability=0.999)
        assert result.availability_ok is True

    def test_evaluate_error_rate_within_budget(self) -> None:
        """``error_rate=0.005 <= 0.01`` → ``error_rate_ok=True``."""
        slo = TenantSLO()
        result = slo.evaluate(error_rate=0.005)
        assert result.error_rate_ok is True
        assert result.within_slo is True

    def test_evaluate_error_rate_exceeds_budget(self) -> None:
        """``error_rate=0.05 > 0.01`` → ``error_rate_ok=False``."""
        slo = TenantSLO()
        result = slo.evaluate(error_rate=0.05)
        assert result.error_rate_ok is False
        assert result.within_slo is False

    def test_evaluate_error_rate_at_boundary(self) -> None:
        """``error_rate=0.01 == 0.01`` → ``error_rate_ok=True`` (<=)."""
        slo = TenantSLO()
        result = slo.evaluate(error_rate=0.01)
        assert result.error_rate_ok is True

    def test_evaluate_all_within_budget(self) -> None:
        """Все метрики within → ``within_slo=True``."""
        slo = TenantSLO()
        result = slo.evaluate(
            latency_p99_ms=100.0,
            availability=0.9999,
            error_rate=0.001,
        )
        assert result.latency_ok is True
        assert result.availability_ok is True
        assert result.error_rate_ok is True
        assert result.within_slo is True

    def test_evaluate_all_exceed_budget(self) -> None:
        """Все метрики exceeded → ``within_slo=False``."""
        slo = TenantSLO()
        result = slo.evaluate(
            latency_p99_ms=1000.0,
            availability=0.9,
            error_rate=0.5,
        )
        assert result.latency_ok is False
        assert result.availability_ok is False
        assert result.error_rate_ok is False
        assert result.within_slo is False

    def test_evaluate_mixed_within_only(self) -> None:
        """Частичные метрики: aggregate считается по available."""
        slo = TenantSLO()
        result = slo.evaluate(latency_p99_ms=200.0, error_rate=0.5)
        assert result.latency_ok is True
        assert result.error_rate_ok is False
        assert result.availability_ok is None
        assert result.within_slo is False

    def test_evaluate_references_slo(self) -> None:
        """``SLOEvaluation.tenant_slo`` ссылается на parent SLO."""
        slo = TenantSLO(latency_p99_ms=300.0)
        result = slo.evaluate(latency_p99_ms=100.0)
        assert result.tenant_slo is slo


class TestSLOEvaluationToLogDict:
    """``SLOEvaluation.to_log_dict()`` — structured log."""

    def test_to_log_dict_keys(self) -> None:
        """Все expected keys присутствуют."""
        slo = TenantSLO()
        result = slo.evaluate(
            latency_p99_ms=200.0,
            availability=0.9999,
            error_rate=0.005,
        )
        log_dict = result.to_log_dict()
        assert "slo.latency_p99_ms" in log_dict
        assert "slo.latency_ok" in log_dict
        assert "slo.availability" in log_dict
        assert "slo.availability_ok" in log_dict
        assert "slo.error_rate" in log_dict
        assert "slo.error_rate_ok" in log_dict
        assert "slo.within_slo" in log_dict
        assert "slo.target_latency_p99_ms" in log_dict
        assert "slo.target_availability" in log_dict
        assert "slo.target_error_rate" in log_dict

    def test_to_log_dict_values_match(self) -> None:
        """Values в log_dict совпадают с evaluation."""
        slo = TenantSLO(
            latency_p99_ms=300.0,
            availability_target=0.9995,
            error_rate_target=0.005,
        )
        result = slo.evaluate(
            latency_p99_ms=100.0,
            availability=0.9999,
            error_rate=0.001,
        )
        log_dict = result.to_log_dict()
        assert log_dict["slo.latency_p99_ms"] == 100.0
        assert log_dict["slo.latency_ok"] is True
        assert log_dict["slo.availability"] == 0.9999
        assert log_dict["slo.availability_ok"] is True
        assert log_dict["slo.error_rate"] == 0.001
        assert log_dict["slo.error_rate_ok"] is True
        assert log_dict["slo.within_slo"] is True
        assert log_dict["slo.target_latency_p99_ms"] == 300.0
        assert log_dict["slo.target_availability"] == 0.9995
        assert log_dict["slo.target_error_rate"] == 0.005

    def test_to_log_dict_with_none_values(self) -> None:
        """``to_log_dict()`` для evaluation без метрик."""
        slo = TenantSLO()
        result = slo.evaluate()
        log_dict = result.to_log_dict()
        assert log_dict["slo.latency_p99_ms"] is None
        assert log_dict["slo.latency_ok"] is None
        assert log_dict["slo.availability"] is None
        assert log_dict["slo.availability_ok"] is None
        assert log_dict["slo.error_rate"] is None
        assert log_dict["slo.error_rate_ok"] is None
        assert log_dict["slo.within_slo"] is True


class TestSLOEvaluationDataclass:
    """``SLOEvaluation`` — frozen dataclass."""

    def test_default_values(self) -> None:
        """``SLOEvaluation()`` defaults."""
        slo = TenantSLO()
        eval_ = SLOEvaluation(tenant_slo=slo)
        assert eval_.tenant_slo is slo
        assert eval_.latency_p99_ms is None
        assert eval_.latency_ok is None
        assert eval_.availability is None
        assert eval_.availability_ok is None
        assert eval_.error_rate is None
        assert eval_.error_rate_ok is None
        assert eval_.within_slo is True

    def test_frozen(self) -> None:
        """``SLOEvaluation`` frozen."""
        slo = TenantSLO()
        eval_ = SLOEvaluation(tenant_slo=slo)
        with pytest.raises((AttributeError, Exception)):
            eval_.within_slo = False  # type: ignore[misc]


class TestSLOModuleExports:
    """Module-level ``__all__`` и exports."""

    def test_all_exports(self) -> None:
        """``__all__`` содержит SLOEvaluation и TenantSLO."""
        from src.backend.core.tenancy import slo

        assert "SLOEvaluation" in slo.__all__
        assert "TenantSLO" in slo.__all__
        assert len(slo.__all__) == 2
