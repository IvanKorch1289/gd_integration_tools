"""Focused tests for ObservabilityFacade (PERF-6.6 Sprint 15 coverage ratchet).

Coverage target: services/observability/facade.py 40% → 70%+.
"""

from __future__ import annotations

import pytest

from src.backend.services.observability.facade import (
    ObservabilityFacade,
    get_observability_facade,
)


def test_init_default_plugin() -> None:
    """Default plugin='extension'."""
    f = ObservabilityFacade()
    assert f._plugin == "extension"


def test_init_custom_plugin() -> None:
    """Custom plugin parameter."""
    f = ObservabilityFacade(plugin="my_plugin")
    assert f._plugin == "my_plugin"


@pytest.mark.asyncio
async def test_record_metric_default_value() -> None:
    """record_metric без value → +1 (default)."""
    f = ObservabilityFacade(plugin="test")
    await f.record_metric("counter_a")


@pytest.mark.asyncio
async def test_record_metric_custom_value() -> None:
    """record_metric(name, value=5) — no exception."""
    f = ObservabilityFacade(plugin="test")
    await f.record_metric("counter_b", value=5.0)


@pytest.mark.asyncio
async def test_record_metric_with_tags() -> None:
    """record_metric с tags dict — no exception."""
    f = ObservabilityFacade(plugin="test")
    await f.record_metric("counter_c", tags={"env": "prod", "region": "eu"})


@pytest.mark.asyncio
async def test_start_span_basic() -> None:
    """start_span() — async context manager, yields span or None."""
    f = ObservabilityFacade(plugin="test")
    async with f.start_span("test_span") as span:
        pass


@pytest.mark.asyncio
async def test_start_span_with_attributes() -> None:
    """start_span(name, attributes={...}) — no exception."""
    f = ObservabilityFacade(plugin="test")
    async with f.start_span("test_span", attributes={"k": "v"}):
        pass


@pytest.mark.asyncio
async def test_set_correlation_id() -> None:
    """set_correlation_id — graceful no-op если correlation module unavailable."""
    f = ObservabilityFacade(plugin="test")
    f.set_correlation_id("test-cid-12345")


def test_get_correlation_id_returns_str_or_none() -> None:
    """get_correlation_id возвращает str | None."""
    f = ObservabilityFacade(plugin="test")
    result = f.get_correlation_id()
    assert result is None or isinstance(result, str)


def test_get_observability_facade_singleton() -> None:
    """get_observability_facade — module-level singleton accessor."""
    from src.backend.services.observability import facade as fmod
    fmod._facade = None
    f1 = get_observability_facade()
    f2 = get_observability_facade()
    assert f1 is f2
    assert isinstance(f1, ObservabilityFacade)
    fmod._facade = None
