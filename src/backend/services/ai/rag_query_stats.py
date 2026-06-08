"""Сбор top-N RAG-запросов per-tenant для cache prewarm (S13 K4 W1).

Хранит счётчики hash(query) → count в Redis ZSET с TTL 30 дней.
Используется :class:`RagCachePrewarmer` для prewarm L2 semantic cache
на startup (top-100 запросов).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("RagQueryStatsCollector",)

logger = get_logger(__name__)


class RagQueryStatsCollector:
    """Счётчик RAG-запросов с Redis backend (+in-memory fallback)."""

    DEFAULT_TTL_SECONDS = 30 * 24 * 3600  # 30 дней

    def __init__(
        self,
        redis_client: Any | None = None,
        *,
        key_prefix: str = "rag:query_count",
        ttl_seconds: int | None = None,
    ) -> None:
        self._redis = redis_client
        self._prefix = key_prefix
        self._ttl = ttl_seconds or self.DEFAULT_TTL_SECONDS
        self._memory: dict[str, Counter] = {}
        self._original: dict[str, dict[str, str]] = {}  # tenant → {hash: query}

    @staticmethod
    def _hash(query: str) -> str:
        return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]

    async def record(self, tenant_id: str, query: str) -> None:
        """Зарегистрировать факт RAG-запроса (idempotent inc)."""
        if not query:
            return
        h = self._hash(query)
        self._original.setdefault(tenant_id, {})[h] = query
        if self._redis is not None:
            try:
                key = f"{self._prefix}:{tenant_id}"
                # ZINCRBY — позволяет ZRANGEBYSCORE для top-N.
                await self._redis.zincrby(key, 1, h)
                await self._redis.expire(key, self._ttl)
                # Сохраняем original query тоже (для prewarm-а).
                await self._redis.hset(f"{self._prefix}:query:{tenant_id}", h, query)
                await self._redis.expire(f"{self._prefix}:query:{tenant_id}", self._ttl)
                return
            except Exception:
                logger.debug("RagQueryStatsCollector: Redis fail, in-memory fallback")
        # Fallback. ``Counter`` здесь — ``collections.Counter`` (счётчик
        # ключей), не ``prometheus_client.Counter`` — violation-check
        # ругается из-за идентичного имени.
        self._memory.setdefault(tenant_id, Counter())[h] += 1

    async def top_queries(self, tenant_id: str, n: int = 100) -> list[tuple[str, int]]:
        """Top-N запросов для tenant'а (по убыванию counter'а)."""
        if self._redis is not None:
            try:
                key = f"{self._prefix}:{tenant_id}"
                items = await self._redis.zrevrange(key, 0, n - 1, withscores=True)
                queries_map = await self._redis.hgetall(
                    f"{self._prefix}:query:{tenant_id}"
                )
                # Распаковка bytes/str.
                normalized: list[tuple[str, int]] = []
                for h_raw, score in items:
                    h = h_raw.decode() if isinstance(h_raw, bytes) else h_raw
                    raw_q = queries_map.get(
                        h.encode()
                        if isinstance(
                            list(queries_map.keys())[0] if queries_map else b"", bytes
                        )
                        else h
                    )
                    if isinstance(raw_q, bytes):
                        raw_q = raw_q.decode()
                    if raw_q:
                        normalized.append((raw_q, int(score)))
                if normalized:
                    return normalized
            except Exception:
                pass
        # Fallback in-memory. ``Counter`` здесь — ``collections.Counter``.
        tenant_counter = self._memory.get(tenant_id, Counter())
        tenant_originals = self._original.get(tenant_id, {})
        result: list[tuple[str, int]] = []
        for h, count in tenant_counter.most_common(n):
            q = tenant_originals.get(h)
            if q:
                result.append((q, count))
        return result
