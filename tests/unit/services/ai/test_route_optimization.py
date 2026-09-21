"""Тесты Sprint 11 K4 W7 — RouteAnalyzer + PRGenerator."""

from __future__ import annotations

from src.backend.services.ai.optimization.pr_generator import PRGenerator
from src.backend.services.ai.optimization.route_analyzer import (
    OptimizationRecommendation,
    RouteAnalyzer,
    RouteMetrics,
)


def test_metrics_groups_by_step_name() -> None:
    """compute_metrics группирует события и считает p50/p95/p99."""
    events = [
        {"step_name": "fetch", "latency_ms": 100.0, "retry_count": 0},
        {"step_name": "fetch", "latency_ms": 200.0, "retry_count": 1},
        {"step_name": "fetch", "latency_ms": 300.0, "retry_count": 0},
        {"step_name": "transform", "latency_ms": 50.0, "error": True},
    ]
    analyzer = RouteAnalyzer()
    metrics = analyzer.compute_metrics(events)
    names = {m.step_name for m in metrics}
    assert names == {"fetch", "transform"}
    fetch = next(m for m in metrics if m.step_name == "fetch")
    assert fetch.request_count == 3
    assert fetch.p95_latency_ms > fetch.p50_latency_ms


def test_slow_step_recommends_parallelization() -> None:
    """p95 > slow_step_p95_ms → kind=parallelization."""
    metrics = [
        RouteMetrics(
            step_name="slow_step",
            request_count=10,
            error_count=0,
            p50_latency_ms=400.0,
            p95_latency_ms=900.0,
            p99_latency_ms=1100.0,
            avg_retry_count=0.0,
        )
    ]
    analyzer = RouteAnalyzer(slow_step_p95_ms=500.0)
    recs = analyzer.recommendations(metrics)
    assert any(r.kind == "parallelization" for r in recs)


def test_high_error_rate_recommends_breaker() -> None:
    """error_rate ≥ threshold → kind=circuit-breaker (P0)."""
    metrics = [
        RouteMetrics(
            step_name="flaky",
            request_count=100,
            error_count=15,
            p50_latency_ms=10,
            p95_latency_ms=20,
            p99_latency_ms=30,
            avg_retry_count=0.0,
        )
    ]
    analyzer = RouteAnalyzer(high_error_rate=0.05)
    recs = analyzer.recommendations(metrics)
    breaker_recs = [r for r in recs if r.kind == "circuit-breaker"]
    assert len(breaker_recs) == 1
    assert breaker_recs[0].priority == "P0"


def test_pr_generator_renders_summary_and_table() -> None:
    """PRGenerator.render возвращает markdown с заголовком, таблицей и recs."""
    metrics = [
        RouteMetrics(
            step_name="step_a",
            request_count=5,
            error_count=0,
            p50_latency_ms=10,
            p95_latency_ms=50,
            p99_latency_ms=80,
            avg_retry_count=0,
        )
    ]
    recs = [
        OptimizationRecommendation(
            step_name="step_a",
            kind="caching",
            rationale="cache static response",
            priority="P1",
            estimated_gain_ms=20.0,
        )
    ]
    markdown = PRGenerator.render("my-route", metrics, recs)
    assert "AI Route Optimization" in markdown
    assert "my-route" in markdown
    assert "step_a" in markdown
    assert "P1" in markdown
