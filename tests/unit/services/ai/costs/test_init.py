"""Unit-тесты ``services.ai.costs`` — coverage ratchet (Post-Plan A Sprint 13).

core/ai/costs service package facade (Wave D.5 + K4 S6 W3 dashboard):
re-exports 8 symbols (AICostDashboard, CostAlert, CostAlertService,
CostByTenant, DashboardSnapshot, LangFuseReader, TokenRateTrend, UsageByModel).
~10 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai import costs
from src.backend.services.ai.costs import (
    AICostDashboard,
    CostAlert,
    CostAlertService,
    CostByTenant,
    DashboardSnapshot,
    LangFuseReader,
    TokenRateTrend,
    UsageByModel,
)


@pytest.mark.unit
class TestCostsFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "AICostDashboard",
            "CostAlert",
            "CostAlertService",
            "CostByTenant",
            "DashboardSnapshot",
            "LangFuseReader",
            "TokenRateTrend",
            "UsageByModel",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(costs, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in costs.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 8 символов."""
        assert len(costs.__all__) == 8

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает cost-аналитику AI Stack."""
        assert costs.__doc__ is not None
        assert "cost" in costs.__doc__.lower() or "AI" in costs.__doc__


@pytest.mark.unit
class TestCostsFacadeIdentity:
    """Identity checks для 8 re-exports."""

    def test_ai_cost_dashboard_is_class(self) -> None:
        """``AICostDashboard`` — class (dashboard)."""
        assert isinstance(AICostDashboard, type)

    def test_cost_alert_is_class(self) -> None:
        """``CostAlert`` — class (alert dataclass)."""
        assert isinstance(CostAlert, type)

    def test_cost_alert_service_is_class(self) -> None:
        """``CostAlertService`` — class (alert service)."""
        assert isinstance(CostAlertService, type)

    def test_cost_by_tenant_is_class(self) -> None:
        """``CostByTenant`` — class (aggregation dataclass)."""
        assert isinstance(CostByTenant, type)

    def test_dashboard_snapshot_is_class(self) -> None:
        """``DashboardSnapshot`` — class (snapshot dataclass)."""
        assert isinstance(DashboardSnapshot, type)

    def test_lang_fuse_reader_is_class(self) -> None:
        """``LangFuseReader`` — class (LangFuse data reader)."""
        assert isinstance(LangFuseReader, type)

    def test_token_rate_trend_is_class(self) -> None:
        """``TokenRateTrend`` — class (trend aggregation)."""
        assert isinstance(TokenRateTrend, type)

    def test_usage_by_model_is_class(self) -> None:
        """``UsageByModel`` — class (usage aggregation)."""
        assert isinstance(UsageByModel, type)
