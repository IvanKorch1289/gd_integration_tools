"""Unit-тесты ``core.api.cache`` — coverage ratchet (S48 W15).

core/api/cache.py — Sprint 38 R13 FIX facade: re-export canonical cache
primitives (``get_cache_metrics_snapshot``, ``get_metrics_snapshot``) для
lazy proxy resolution в services.cache.metrics. 5 statements, 0% coverage.

Цель slice: 0% → 100% через проверку imports + identity check.
"""

from __future__ import annotations

import pytest

from src.backend.core.api.cache import (
    get_cache_metrics_snapshot,
    get_metrics_snapshot,
    metrics_collector,
    rag_metrics,
)


@pytest.mark.unit
class TestCacheFacade:
    """Smoke-тесты на R13-fix facade."""

    def test_get_cache_metrics_snapshot_is_callable(self) -> None:
        """``get_cache_metrics_snapshot`` — callable."""
        assert callable(get_cache_metrics_snapshot)

    def test_get_metrics_snapshot_is_callable(self) -> None:
        """``get_metrics_snapshot`` — callable."""
        assert callable(get_metrics_snapshot)

    def test_metrics_collector_module_exported(self) -> None:
        """``metrics_collector`` module re-exported."""
        assert metrics_collector is not None
        assert hasattr(metrics_collector, "get_cache_metrics_snapshot")

    def test_rag_metrics_module_exported(self) -> None:
        """``rag_metrics`` module re-exported."""
        assert rag_metrics is not None
        assert hasattr(rag_metrics, "get_metrics_snapshot")
