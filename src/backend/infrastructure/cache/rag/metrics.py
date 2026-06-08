"""Prometheus-метрики 3-tier RAG cache (К4 MVP, Шаг 2)."""

from __future__ import annotations

from typing import Any

from src.backend.infrastructure.logging.factory import get_logger

logger = get_logger(__name__)

__all__ = ("get_metrics_snapshot", "record_hit", "record_miss")

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
        from src.backend.infrastructure.observability.metrics_registry import (
            metrics_registry,
        )

        _hits = metrics_registry.counter(
            "rag_cache_hits_total", "RAG cache hits per tier", labels=("tier",)
        )
        _misses = metrics_registry.counter(
            "rag_cache_misses_total", "RAG cache misses per tier", labels=("tier",)
        )
    except ImportError:
        logger.debug("MetricsRegistry недоступен — RAG cache metrics в no-op.")
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
