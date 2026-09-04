"""Tests for services/cache/metrics.py (S98 — coverage push).

PEP 562 lazy proxy to infrastructure.cache.metrics_collector.
"""

from __future__ import annotations


def test_module_dunder_all() -> None:
    """__all__ = ('get_cache_metrics_snapshot', 'get_metrics_snapshot')."""
    import src.backend.services.cache.metrics as mod

    assert mod.__all__ == ("get_cache_metrics_snapshot", "get_metrics_snapshot")


def test_get_cache_metrics_snapshot_is_lazy_proxy() -> None:
    """Accessing get_cache_metrics_snapshot triggers lazy import из core.api.cache."""
    from src.backend.core.api.cache import get_cache_metrics_snapshot as canonical
    from src.backend.services.cache import metrics

    # Lazy proxy resolves to canonical function (identity check).
    assert metrics.get_cache_metrics_snapshot is canonical


def test_get_metrics_snapshot_is_lazy_proxy() -> None:
    """Accessing get_metrics_snapshot triggers lazy import из core.api.cache."""
    from src.backend.core.api.cache import get_metrics_snapshot as canonical
    from src.backend.services.cache import metrics

    assert metrics.get_metrics_snapshot is canonical


def test_lazy_proxy_unknown_attr_raises() -> None:
    """Unknown attribute → AttributeError (PEP 562 contract)."""
    import src.backend.services.cache.metrics as mod

    with pytest.raises(AttributeError, match="module"):
        mod.does_not_exist  # type: ignore[attr-defined]


import pytest
