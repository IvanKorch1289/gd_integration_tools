"""Unit tests for SLOTracker + enforce_slo decorator."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.backend.infrastructure.application.slo_tracker import (
    SLOBudgetExceeded,
    SLOTracker,
    enforce_slo,
)


class TestSLOTracker:
    def test_record_and_percentiles(self) -> None:
        tracker = SLOTracker()
        for i in range(1, 101):
            tracker.record("route_a", latency_ms=float(i))
        stats = tracker.get_route_stats("route_a")
        assert stats["total"] == 100
        # HdrHistogram percentile may be off by 1 due to bucketing
        assert stats["p50_ms"] == pytest.approx(50.0, abs=2.0)
        assert stats["p95_ms"] == pytest.approx(95.0, abs=2.0)
        assert stats["p99_ms"] == pytest.approx(99.0, abs=2.0)

    def test_error_rate(self) -> None:
        tracker = SLOTracker()
        tracker.record("route_b", latency_ms=10.0, is_error=False)
        tracker.record("route_b", latency_ms=20.0, is_error=True)
        stats = tracker.get_route_stats("route_b")
        assert stats["error_rate"] == 50.0

    def test_check_budget_healthy(self) -> None:
        tracker = SLOTracker()
        tracker.record("route_c", latency_ms=10.0, is_error=False)
        assert tracker.check_budget("route_c", max_error_rate=5.0) is True

    def test_check_budget_exceeded(self) -> None:
        tracker = SLOTracker()
        tracker.record("route_d", latency_ms=10.0, is_error=True)
        assert tracker.check_budget("route_d", max_error_rate=5.0) is False

    def test_check_budget_no_data(self) -> None:
        tracker = SLOTracker()
        assert tracker.check_budget("unknown", max_error_rate=5.0) is True


class TestEnforceSLO:
    @pytest.mark.asyncio
    async def test_enforce_slo_allows_healthy(self) -> None:
        tracker = SLOTracker()
        tracker.record("good_route", latency_ms=10.0, is_error=False)

        with patch(
            "src.backend.infrastructure.application.slo_tracker.get_slo_tracker",
            return_value=tracker,
        ):

            @enforce_slo("good_route", max_error_rate=5.0)
            async def handler() -> str:
                return "ok"

            assert await handler() == "ok"

    @pytest.mark.asyncio
    async def test_enforce_slo_rejects_over_budget(self) -> None:
        tracker = SLOTracker()
        tracker.record("bad_route", latency_ms=10.0, is_error=True)

        with patch(
            "src.backend.infrastructure.application.slo_tracker.get_slo_tracker",
            return_value=tracker,
        ):

            @enforce_slo("bad_route", max_error_rate=5.0)
            async def handler() -> str:
                return "ok"

            with pytest.raises(SLOBudgetExceeded, match="SLO budget exceeded"):
                await handler()
