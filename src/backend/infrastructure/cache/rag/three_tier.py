"""Фасад 3-tier RAG cache: lookup L1 → L2 → L3 + store."""

from __future__ import annotations

import logging
from typing import Any

from src.backend.infrastructure.cache.rag.exact import L1ExactCache
from src.backend.infrastructure.cache.rag.invalidation import RagInvalidationBus
from src.backend.infrastructure.cache.rag.metrics import get_metrics_snapshot
from src.backend.infrastructure.cache.rag.retrieval import L3RetrievalCache
from src.backend.infrastructure.cache.rag.semantic import L2SemanticRagCache

logger = logging.getLogger(__name__)

__all__ = ("ThreeTierRagCache",)


class ThreeTierRagCache:
    """Координатор трёх tier'ов кэша + invalidation hooks."""

    def __init__(
        self,
        l1: L1ExactCache | None = None,
        l2: L2SemanticRagCache | None = None,
        l3: L3RetrievalCache | None = None,
        bus: RagInvalidationBus | None = None,
        l1_enabled: bool = True,
        l2_enabled: bool = False,
        l3_enabled: bool = True,
    ) -> None:
        self._l1 = l1 or L1ExactCache()
        self._l2 = l2 or L2SemanticRagCache()
        self._l3 = l3 or L3RetrievalCache()
        self._bus = bus
        self._l1_enabled = l1_enabled
        self._l2_enabled = l2_enabled
        self._l3_enabled = l3_enabled

    async def lookup_answer(
        self, query: str, *, tenant: str | None = None
    ) -> tuple[Any | None, str | None]:
        """Ищет готовый ответ в L1 → L2. Возвращает (value, tier|None)."""
        if self._l1_enabled:
            value = await self._l1.get(query, tenant=tenant)
            if value is not None:
                return value, "l1"
        if self._l2_enabled:
            value = await self._l2.get(query, tenant=tenant)
            if value is not None:
                return value, "l2"
        return None, None

    async def lookup_chunks(
        self, query: str, *, namespace: str | None = None
    ) -> tuple[list[dict[str, Any]] | None, str | None]:
        """Ищет сырые retrieval-чанки в L3."""
        if not self._l3_enabled:
            return None, None
        chunks = await self._l3.get(query, namespace=namespace)
        if chunks is not None:
            return chunks, "l3"
        return None, None

    async def store_answer(
        self, query: str, value: Any, *, tenant: str | None = None
    ) -> None:
        """Сохраняет ответ в активные tier'ы (L1 + L2 при включении)."""
        if self._l1_enabled:
            await self._l1.set(query, value, tenant=tenant)
        if self._l2_enabled:
            await self._l2.set(query, value, tenant=tenant)

    async def store_chunks(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        *,
        namespace: str | None = None,
    ) -> None:
        if self._l3_enabled:
            await self._l3.set(query, chunks, namespace=namespace)

    async def invalidate_by_tag(self, tag: str) -> int:
        """Публикует invalidate-событие. Подписчики реагируют по тегу."""
        if self._bus is None:
            return 0
        return await self._bus.publish(tag=tag)

    async def flush(self, tier: str | None = None) -> dict[str, int]:
        """Очистка одного tier или всех (admin-action)."""
        result: dict[str, int] = {}
        if tier in (None, "l1") and self._l1_enabled:
            result["l1"] = await self._l1.flush()
        if tier in (None, "l2") and self._l2_enabled:
            result["l2"] = await self._l2.flush()
        if tier in (None, "l3") and self._l3_enabled:
            result["l3"] = await self._l3.flush()
        return result

    @staticmethod
    def stats() -> dict[str, dict[str, int]]:
        """Снимок hit/miss-счётчиков (read-only)."""
        return get_metrics_snapshot()
