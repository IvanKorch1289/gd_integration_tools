"""Prometheus-метрики 3-tier RAG cache (К4 MVP, Шаг 2)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("record_hit", "record_miss", "get_metrics_snapshot")

_hits: Any = None
_misses: Any = None
_initialized = False
_snapshot: dict[str, dict[str, int]] = {
    "hits": {"l1": 0, "l2": 0, "l3": 0},
    "misses": {"l1": 0, "l2": 0, "l3": 0},
}


def _ensure() -> None:
    global _hits, _misses, _initialized
    if _initialized:
        return
    try:
        from prometheus_client import Counter

        _hits = Counter(
            "rag_cache_hits_total",
            "RAG cache hits per tier",
            labelnames=("tier",),
        )
        _misses = Counter(
            "rag_cache_misses_total",
            "RAG cache misses per tier",
            labelnames=("tier",),
        )
    except ImportError:
        logger.debug("prometheus_client недоступен — RAG cache metrics в no-op.")
    finally:
        _initialized = True


def record_hit(tier: str) -> None:
    """Увеличивает счётчик cache-hit в указанном tier (l1/l2/l3)."""
    _ensure()
    _snapshot["hits"][tier] = _snapshot["hits"].get(tier, 0) + 1
    if _hits is not None:
        _hits.labels(tier=tier).inc()


def record_miss(tier: str) -> None:
    """Увеличивает счётчик cache-miss в указанном tier."""
    _ensure()
    _snapshot["misses"][tier] = _snapshot["misses"].get(tier, 0) + 1
    if _misses is not None:
        _misses.labels(tier=tier).inc()


def get_metrics_snapshot() -> dict[str, dict[str, int]]:
    """Plain-snapshot счётчиков (для admin-endpoint, без pull из Prometheus)."""
    return {"hits": dict(_snapshot["hits"]), "misses": dict(_snapshot["misses"])}
