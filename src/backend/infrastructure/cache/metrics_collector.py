"""Metrics collector for all cache tiers (LRU, RAG, semantic).

Aggregates hit/miss counters from all tiers into a single snapshot
for the admin API endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.infrastructure.cache.rag.metrics import get_metrics_snapshot as get_rag_metrics_snapshot

logger = logging.getLogger(__name__)

__all__ = ("get_cache_metrics_snapshot",)

# Local snapshot for LRU metrics (mirrors rag/metrics.py pattern)
_lru_snapshot: dict[str, int] = {
    "lru_cache_hits": 0,
    "lru_cache_misses": 0,
}


def _ensure_lru_metrics() -> None:
    """Lazy-initialize LRU metrics counters."""
    global _lru_snapshot
    try:
        from src.backend.infrastructure.cache.lru_cache import (
            _metric_hits,
            _metric_misses,
        )

        # These are prometheus counters - we can't easily read their values
        # without pulling from prometheus. For the admin API snapshot,
        # we maintain a local counter that gets incremented alongside prometheus.
    except ImportError:
        logger.debug("LRU cache metrics not available")


def record_lru_hit(scope: str = "l1") -> None:
    """Records an LRU cache hit (called by LruMemoryCache)."""
    _lru_snapshot["lru_cache_hits"] += 1


def record_lru_miss(scope: str = "l1") -> None:
    """Records an LRU cache miss (called by LruMemoryCache)."""
    _lru_snapshot["lru_cache_misses"] += 1


def get_cache_metrics_snapshot() -> dict[str, Any]:
    """
    Returns aggregated cache metrics snapshot from all tiers.

    Includes:
    - lru_cache_hits: Total L1 LRU cache hits
    - lru_cache_misses: Total L1 LRU cache misses
    - rag_hits: RAG cache hits per tier (l1, l2, l3)
    - rag_misses: RAG cache misses per tier (l1, l2, l3)
    - semantic_tier_hits: Semantic tier hits (from rag metrics)

    Returns:
        dict with aggregated metrics from all cache tiers.
    """
    # Get RAG metrics
    rag_metrics = get_rag_metrics_snapshot()

    # Aggregate RAG hits/misses by tier
    rag_hits = rag_metrics.get("hits", {})
    rag_misses = rag_metrics.get("misses", {})

    # Total semantic tier hits (from l3)
    semantic_tier_hits = rag_hits.get("l3", 0)

    return {
        "lru_cache_hits": _lru_snapshot.get("lru_cache_hits", 0),
        "lru_cache_misses": _lru_snapshot.get("lru_cache_misses", 0),
        "rag_hits": rag_hits,
        "rag_misses": rag_misses,
        "semantic_tier_hits": semantic_tier_hits,
        "total_lru_hits": _lru_snapshot.get("lru_cache_hits", 0),
        "total_lru_misses": _lru_snapshot.get("lru_cache_misses", 0),
        "total_rag_hits": sum(rag_hits.values()),
        "total_rag_misses": sum(rag_misses.values()),
    }
