"""Sprint 38: cache facade — re-exports canonical cache primitives.

R13 FIX (2026-08-30): expose ``get_cache_metrics_snapshot`` and
``get_metrics_snapshot`` through this facade so the lazy proxy in
:mod:`src.backend.services.cache.metrics` resolves correctly.

Both symbols are concrete callables in :mod:`infrastructure.cache`:

- ``get_cache_metrics_snapshot`` → :func:`infrastructure.cache.metrics_collector.get_cache_metrics_snapshot`
- ``get_metrics_snapshot`` → :func:`infrastructure.cache.rag.metrics.get_metrics_snapshot`

Layer policy: entrypoints → services. services → core.api (facade).
core.api → infrastructure (allowed via facade).
"""
from src.backend.infrastructure.cache import metrics_collector
from src.backend.infrastructure.cache.rag import metrics as rag_metrics

# Re-export concrete callables (not just modules) so lazy proxy
# `__getattr__` in services.cache.metrics resolves without import
# gymnastics. Modules are also re-exported for callsites that prefer
# module-level access.
get_cache_metrics_snapshot = metrics_collector.get_cache_metrics_snapshot
get_metrics_snapshot = rag_metrics.get_metrics_snapshot

__all__ = [
    "metrics_collector",
    "rag_metrics",
    "get_cache_metrics_snapshot",
    "get_metrics_snapshot",
]
