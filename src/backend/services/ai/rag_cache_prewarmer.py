"""Pre-warm L2 semantic cache RAG для top-N запросов tenants (S13 K4 W1).

Запускается из lifespan startup как background task через TaskRegistry.
Throttled (1 query / 100ms по умолчанию) чтобы не положить Qdrant.

Метрики:

* ``rag_prewarm_loaded_total{tenant}``;
* ``rag_prewarm_duration_seconds{tenant}``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.services.ai.rag_query_stats import RagQueryStatsCollector

__all__ = ("RagCachePrewarmer",)

logger = logging.getLogger(__name__)

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
except Exception:  # noqa: BLE001, S110
    _PREWARM_COUNTER = None  # type: ignore[assignment]
    _PREWARM_DURATION = None  # type: ignore[assignment]


class RagCachePrewarmer:
    """Pre-warm top-N RAG queries для каждого opt-in tenant'а."""

    def __init__(
        self,
        *,
        rag_service: Any,
        stats_collector: "RagQueryStatsCollector",
        top_n: int = 100,
        throttle_ms: int = 100,
    ) -> None:
        self._rag = rag_service
        self._stats = stats_collector
        self._top_n = top_n
        self._throttle = throttle_ms / 1000.0

    async def prewarm_tenant(self, tenant_id: str) -> int:
        """Pre-warm для одного tenant; возвращает количество прогретых query."""
        start = time.monotonic()
        loaded = 0
        try:
            top = await self._stats.top_queries(tenant_id, n=self._top_n)
            for query, _count in top:
                try:
                    await self._rag.query(query, fill_cache=True, tenant_id=tenant_id)
                except TypeError:
                    # Если RAG-сервис не поддерживает fill_cache — fallback на обычный query.
                    try:
                        await self._rag.query(query, tenant_id=tenant_id)
                    except Exception:  # noqa: BLE001, S112
                        continue
                except Exception as exc:  # noqa: BLE001, S110
                    logger.debug("rag_prewarm.query_failed: %s", exc)
                    continue
                loaded += 1
                await asyncio.sleep(self._throttle)
        except Exception:  # noqa: BLE001, S110
            logger.exception("rag_prewarm.tenant_failed tenant=%s", tenant_id)

        duration = time.monotonic() - start
        if _PREWARM_COUNTER is not None:
            try:
                _PREWARM_COUNTER.labels(tenant=tenant_id).inc(loaded)
            except Exception:  # noqa: BLE001, S110
                pass
        if _PREWARM_DURATION is not None:
            try:
                _PREWARM_DURATION.labels(tenant=tenant_id).observe(duration)
            except Exception:  # noqa: BLE001, S110
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
