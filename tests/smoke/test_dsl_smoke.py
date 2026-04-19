"""Smoke tests — минимальная проверка что DSL и процессоры не сломаны."""

from __future__ import annotations

import pytest


def test_builder_from_creates_route():
    """RouteBuilder.from_() должен создавать builder без ошибок."""
    from app.dsl.builder import RouteBuilder

    builder = RouteBuilder.from_("test.route", source="internal:test")
    assert builder.route_id == "test.route"
    assert builder.source == "internal:test"


def test_builder_fluent_chain():
    """Fluent chain должен возвращать RouteBuilder."""
    from app.dsl.builder import RouteBuilder

    pipeline = (
        RouteBuilder.from_("test.chain", source="internal:test")
        .set_header("x-test", "1")
        .set_property("domain", "test")
        .log(level="info")
        .build()
    )
    assert pipeline.route_id == "test.chain"
    assert len(pipeline.processors) == 3


def test_eip_package_imports():
    """Все 22 EIP процессора должны импортироваться из app.dsl.engine.processors.eip."""
    from app.dsl.engine.processors.eip import (
        DeadLetterProcessor,
        IdempotentConsumerProcessor,
        FallbackChainProcessor,
        WireTapProcessor,
        MessageTranslatorProcessor,
        DynamicRouterProcessor,
        ScatterGatherProcessor,
        ThrottlerProcessor,
        DelayProcessor,
        SplitterProcessor,
        AggregatorProcessor,
        RecipientListProcessor,
        LoadBalancerProcessor,
        CircuitBreakerProcessor,
        ClaimCheckProcessor,
        NormalizerProcessor,
        ResequencerProcessor,
        MulticastProcessor,
        LoopProcessor,
        OnCompletionProcessor,
        SortProcessor,
        TimeoutProcessor,
    )
    assert DeadLetterProcessor is not None


def test_rpa_processors_import():
    """RPA процессоры доступны."""
    from app.dsl.engine.processors.rpa import (
        PdfReadProcessor,
        ExcelReadProcessor,
        ImageOcrProcessor,
        RegexProcessor,
    )
    assert PdfReadProcessor is not None


def test_dsl_ergonomics_v2():
    """DSL v2 методы (.as_, .pick, .drop, .batch_by_field) существуют."""
    from app.dsl.builder import RouteBuilder

    builder = RouteBuilder.from_("test.v2", source="internal:test")
    assert hasattr(builder, "as_")
    assert hasattr(builder, "on_error")
    assert hasattr(builder, "filter_dispatch")
    assert hasattr(builder, "pick")
    assert hasattr(builder, "drop")
    assert hasattr(builder, "batch_by_field")
    assert hasattr(builder, "poll_and_aggregate")


def test_managed_async_client_base():
    """ManagedAsyncClient base доступен."""
    from app.infrastructure.clients.base import ManagedAsyncClient
    assert ManagedAsyncClient is not None


def test_health_aggregator_singleton():
    """HealthAggregator singleton."""
    from app.infrastructure.application.health_aggregator import get_health_aggregator

    agg1 = get_health_aggregator()
    agg2 = get_health_aggregator()
    assert agg1 is agg2


def test_slo_tracker_percentiles():
    """SLOTracker корректно считает percentiles."""
    from app.infrastructure.application.slo_tracker import SLOTracker

    tracker = SLOTracker()
    for latency in [10, 20, 30, 40, 50, 100, 200, 500, 1000, 2000]:
        tracker.record("test.route", latency, is_error=False)

    stats = tracker.get_route_stats("test.route")
    assert stats["total"] == 10
    assert stats["p50_ms"] > 0
    assert stats["p99_ms"] > stats["p50_ms"]
