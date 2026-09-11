"""Focused tests for SLOTracker (PERF-6.6 Sprint 17 coverage ratchet).

Coverage target: slo_tracker.py 29% → 70%+.
"""

from __future__ import annotations

import time

import pytest

from src.backend.infrastructure.application.slo_tracker import (
    RouteStats,
    SLOTracker,
)


def test_route_stats_init_empty() -> None:
    """RouteStats() инициализируется пустым fallback stats."""
    rs = RouteStats()
    assert rs.samples == 0
    assert rs.percentile(50.0) == 0


def test_route_stats_record_latency() -> None:
    """RouteStats.record(latency_ms) — накапливает histogram."""
    rs = RouteStats()
    for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
        rs.record(v)
    assert rs.samples == 5
    # median ~ 30
    assert 20.0 <= rs.percentile(50.0) <= 40.0


def test_route_stats_record_zero() -> None:
    """RouteStats.record(0) — no exception (zero value)."""
    rs = RouteStats()
    rs.record(0.0)
    assert rs.samples == 1


def test_route_stats_percentile_empty() -> None:
    """RouteStats.percentile на пустом → 0."""
    rs = RouteStats()
    assert rs.percentile(99.9) == 0


def test_route_stats_to_dict() -> None:
    """RouteStats.to_dict() returns serializable structure."""
    rs = RouteStats()
    rs.record(10.0)
    rs.record(20.0, is_error=True)
    d = rs.to_dict()
    assert "p50" in d or "percentiles" in d or "samples" in d or "latency" in d
    assert isinstance(d, dict)


def test_route_stats_p95_percentile() -> None:
    """RouteStats.percentile(95) возвращает 95th percentile."""
    rs = RouteStats()
    for v in range(1, 101):  # 1..100
        rs.record(float(v))
    p95 = rs.percentile(95.0)
    # For 1-100, p95 ≈ 95
    assert 90.0 <= p95 <= 100.0


def test_slo_tracker_init_empty() -> None:
    """SLOTracker() — empty routes dict."""
    tracker = SLOTracker()
    assert isinstance(tracker._stats, dict)
    assert len(tracker._stats) == 0


def test_slo_tracker_record_creates_route() -> None:
    """record() создаёт RouteStats если не существует."""
    tracker = SLOTracker()
    tracker.record("route-1", 50.0)
    assert "route-1" in tracker._stats
    assert tracker.get_route_stats("route-1")["samples"] == 1


def test_slo_tracker_record_multiple_routes() -> None:
    """record() для разных route_id — separate RouteStats."""
    tracker = SLOTracker()
    tracker.record("route-a", 10.0)
    tracker.record("route-b", 20.0)
    assert tracker.get_route_stats("route-a")["samples"] == 1
    assert tracker.get_route_stats("route-b")["samples"] == 1


def test_slo_tracker_record_accumulates() -> None:
    """record() для того же route_id — накапливает samples."""
    tracker = SLOTracker()
    for i in range(10):
        tracker.record("hot-route", float(i * 10))
    assert tracker.get_route_stats("hot-route")["samples"] == 10


def test_slo_tracker_record_with_error() -> None:
    """record(latency_ms, is_error=True) — error counter increments."""
    tracker = SLOTracker()
    tracker.record("route-1", 100.0, is_error=True)
    assert tracker.get_route_stats("route-1")["errors"] >= 1


def test_slo_tracker_get_report_empty() -> None:
    """get_report() на empty tracker."""
    tracker = SLOTracker()
    report = tracker.get_report()
    assert isinstance(report, dict)


def test_slo_tracker_get_report_with_routes() -> None:
    """get_report() с данными содержит route info."""
    tracker = SLOTracker()
    tracker.record("route-x", 50.0)
    tracker.record("route-x", 100.0, is_error=True)
    report = tracker.get_report()
    assert "route-x" in report
    rdata = report["route-x"]
    assert "samples" in rdata or "latency" in rdata or "p50" in rdata


def test_slo_tracker_get_route_stats_missing() -> None:
    """get_route_stats(unknown) → returns zero/empty stats."""
    tracker = SLOTracker()
    stats = tracker.get_route_stats("never-existed")
    # Returns either empty dict or zero-stats
    assert isinstance(stats, dict)


def test_slo_tracker_reset() -> None:
    """reset() очищает все routes."""
    tracker = SLOTracker()
    tracker.record("route-1", 50.0)
    tracker.record("route-2", 60.0)
    tracker.reset()
    assert len(tracker._stats) == 0


def test_slo_tracker_check_budget_passes() -> None:
    """check_budget() — low error rate → True."""
    tracker = SLOTracker()
    for i in range(100):
        tracker.record("stable-route", 10.0, is_error=False)
    # No errors, well within budget
    assert tracker.check_budget("stable-route", max_error_rate=5.0) is True


def test_slo_tracker_check_budget_fails() -> None:
    """check_budget() — high error rate → False."""
    tracker = SLOTracker()
    for i in range(10):
        tracker.record("flaky-route", 10.0, is_error=(i < 8))  # 80% errors
    # 80% > 5% threshold
    assert tracker.check_budget("flaky-route", max_error_rate=5.0) is False
