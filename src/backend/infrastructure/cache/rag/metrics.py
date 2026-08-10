"""Prometheus-метрики 3-tier RAG cache (К4 MVP, Шаг 2).

Round 5 Imp.4 (Sprint 2.1 followup): добавлен label ``version`` в
метрики ``rag_cache_hits_total`` и ``rag_cache_misses_total``. Это
позволяет разделять legacy-ключи ``rag:l3:*`` (без ``v2``) от
текущих ``rag:l3:v2:*`` через ``metrics.labels(tier=..., version=...)``
и видеть в Grafana, есть ли вообще legacy-нагрузка после cutover.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

__all__ = ("get_metrics_snapshot", "record_hit", "record_miss")

_hits: Any = None
_misses: Any = None
_initialized = False
_snapshot: dict[str, dict[str, int]] = {
    "hits": {"l1": 0, "l2": 0, "l3": 0},
    "misses": {"l1": 0, "l2": 0, "l3": 0},
}

# Версия текущего key-scheme (синхронизирована с
# src.backend.infrastructure.cache.rag.retrieval.L3RetrievalCache.PREFIX).
# "v2" = rag:l3:v2:* (current), "legacy" = rag:l3:* без v2 (carried over
# после cutover, см. Sprint 2.1).
DEFAULT_VERSION = "v2"


def _ensure() -> None:
    global _hits, _misses, _initialized
    if _initialized:
        return
    try:
        from src.backend.core.utils.metrics_registry import metrics_registry

        _hits = metrics_registry.counter(
            "rag_cache_hits_total",
            "RAG cache hits per tier",
            labels=("tier", "version"),
        )
        _misses = metrics_registry.counter(
            "rag_cache_misses_total",
            "RAG cache misses per tier",
            labels=("tier", "version"),
        )
    except ImportError:
        logger.debug("MetricsRegistry недоступен — RAG cache metrics в no-op.")
    finally:
        _initialized = True


def record_hit(tier: str, *, version: str = DEFAULT_VERSION) -> None:
    """Увеличивает счётчик cache-hit в указанном tier (l1/l2/l3).

    Args:
        tier: Уровень кэша (``"l1"``, ``"l2"``, ``"l3"``).
        version: Версия key-scheme (``"v2"`` default, ``"legacy"`` для
            carry-over ключей ``rag:l3:*`` без префикса ``v2``).

    """
    _ensure()
    _snapshot["hits"][tier] = _snapshot["hits"].get(tier, 0) + 1
    if _hits is not None:
        _hits.labels(tier=tier, version=version).inc()


def record_miss(tier: str, *, version: str = DEFAULT_VERSION) -> None:
    """Увеличивает счётчик cache-miss в указанном tier.

    Args:
        tier: Уровень кэша.
        version: Версия key-scheme (см. :func:`record_hit`).

    """
    _ensure()
    _snapshot["misses"][tier] = _snapshot["misses"].get(tier, 0) + 1
    if _misses is not None:
        _misses.labels(tier=tier, version=version).inc()


def get_metrics_snapshot() -> dict[str, dict[str, int]]:
    """Plain-snapshot счётчиков (для admin-endpoint, без pull из Prometheus)."""
    return {"hits": dict(_snapshot["hits"]), "misses": dict(_snapshot["misses"])}
