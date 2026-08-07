"""Pre-warm L2 semantic cache RAG для top-N запросов tenants (S13 K4 W1).

Запускается из lifespan startup как background task через TaskRegistry.
Throttled (1 query / 100ms по умолчанию) чтобы не положить Qdrant.

Метрики:

* ``rag_prewarm_loaded_total{tenant}``;
* ``rag_prewarm_duration_seconds{tenant}``.

cycle-5/D-AUDIT-506: ``RagCachePrewarmer`` вызывает ``RAGService.search()``
(а не phantom ``query(query, fill_cache=True, ...)``). L3 cache заполняется
внутри ``search()`` при ``self._cache is not None`` — никаких отдельных
``fill_cache`` kwargs не требуется.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.services.ai.rag_query_stats import RagQueryStatsCollector

__all__ = ("RagCachePrewarmer",)

logger = get_logger(__name__)

try:  # pragma: no cover
    from prometheus_client import Counter as _PromCounter
    from prometheus_client import Histogram as _PromHistogram

    _PREWARM_COUNTER = _PromCounter(
        "rag_prewarm_loaded_total", "RAG queries prewarmed", ("tenant",)
    )
    _PREWARM_DURATION = _PromHistogram(
        "rag_prewarm_duration_seconds",
        "RAG prewarm duration",
        ("tenant",),
        buckets=(0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0),
    )
except Exception:
    _PREWARM_COUNTER = None  # type: ignore[assignment,unused-ignore]
    _PREWARM_DURATION = None  # type: ignore[assignment,unused-ignore]


class RagCachePrewarmer:
    """Pre-warm top-N RAG queries для каждого opt-in tenant'а.

    cycle-5/D-AUDIT-506: ``prewarm_tenant`` вызывает
    ``self._rag.search(query, tenant_id=...)`` — единственный публичный
    retrieval-метод ``RAGService`` (см. ``rag_service/search_mixin.py:179``).
    Старый ``self._rag.query(query, fill_cache=True, ...)`` был phantom:
    ``query()`` не существует в ``RAGService``, ``fill_cache`` ни одним
    retrieval-методом не принимается (L3 cache заполняется внутри ``search()``).
    """

    def __init__(
        self,
        *,
        rag_service: Any,
        stats_collector: RagQueryStatsCollector,
        top_n: int = 100,
        throttle_ms: int = 100,
    ) -> None:
        self._rag = rag_service
        self._stats = stats_collector
        self._top_n = top_n
        self._throttle = throttle_ms / 1000.0

    async def prewarm_tenant(self, tenant_id: str) -> int:
        """Pre-warm для одного tenant; возвращает количество прогретых query.

        cycle-5/D-AUDIT-506: используется ``RAGService.search(query, tenant_id=...)``.
        ``fill_cache`` — phantom kwarg: L3 cache заполняется в ``search()`` при
        активном ``self._cache`` (см. ``search_mixin.py:227-231``).
        """
        start = time.monotonic()
        loaded = 0
        try:
            top = await self._stats.top_queries(tenant_id, n=self._top_n)
            for query, _count in top:
                # search() сам наполняет L3-кэш при self._cache is not None.
                try:
                    await self._rag.search(query, tenant_id=tenant_id)
                except Exception as exc:
                    logger.debug("rag_prewarm.search_failed tenant=%s query=%r: %s", tenant_id, query, exc)
                    continue
                loaded += 1
                await asyncio.sleep(self._throttle)
        except Exception:
            logger.exception("rag_prewarm.tenant_failed tenant=%s", tenant_id)

        duration = time.monotonic() - start
        if _PREWARM_COUNTER is not None:
            try:
                _PREWARM_COUNTER.labels(tenant=tenant_id).inc(loaded)
            except Exception:
                pass
        if _PREWARM_DURATION is not None:
            try:
                _PREWARM_DURATION.labels(tenant=tenant_id).observe(duration)
            except Exception:
                pass
        logger.info(
            "rag_prewarm.tenant_done",
            extra={
                "tenant": tenant_id,
                "loaded": loaded,
                "duration_seconds": round(duration, 3),
            },
        )
        return loaded

    async def prewarm_all_tenants(self, tenant_ids: list[str]) -> dict[str, int]:
        """Pre-warm для всех указанных tenants. Возвращает {tenant: loaded}."""
        results: dict[str, int] = {}
        for tid in tenant_ids:
            results[tid] = await self.prewarm_tenant(tid)
        return results
