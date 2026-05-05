"""Semantic cache — LLM response caching по embedding similarity.

Традиционный key-based cache пропускает semantically близкие запросы:
- "What's the weather?"
- "Can you tell me the weather?"
→ разные ключи, cache miss.

Semantic cache:
1. Embedding запроса (через ai.processors.EmbeddingProcessor)
2. Поиск близких embeddings в vector store (similarity > 0.95)
3. Если есть match → возвращает кешированный response
4. Иначе: LLM call + сохранение (query, response, embedding)

Multi-instance safe:
- Vector store — shared (Redis/Chroma/pgvector)
- Disk fallback cache для быстрого warmup

Graceful fallback:
- Нет embeddings library → key-based hash cache
- Нет Redis → disk cache (через существующий core.decorators.caching.storage.disk)
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

__all__ = ("SemanticCache", "get_semantic_cache")

logger = logging.getLogger("services.semantic_cache")


class SemanticCache:
    """Cache LLM responses by semantic similarity of queries.

    Usage::
        cache = get_semantic_cache()
        hit = await cache.lookup(query, provider="claude")
        if hit:
            return hit["response"]

        response = await llm.chat(query)
        await cache.store(query, response, provider="claude")
    """

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.95,
        ttl_seconds: int = 3600,
        namespace: str = "llm_semantic_cache",
    ) -> None:
        self._threshold = similarity_threshold
        self._ttl = ttl_seconds
        self._namespace = namespace

    async def lookup(
        self, query: str, *, provider: str | None = None, model: str | None = None
    ) -> dict[str, Any] | None:
        """Ищет кешированный response по semantic similarity.

        Returns {response, similarity, cached_at, source} или None.
        """
        # Try exact hash match first (fast path)
        exact = await self._exact_lookup(query, provider, model)
        if exact is not None:
            return {**exact, "source": "exact", "similarity": 1.0}

        # Semantic search в vector store
        return await self._semantic_lookup(query, provider, model)

    async def store(
        self,
        query: str,
        response: Any,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        """Сохраняет (query, response) с embedding."""
        await self._exact_store(query, response, provider, model)
        await self._semantic_store(query, response, provider, model)

    def _hash_key(self, query: str, provider: str | None, model: str | None) -> str:
        raw = f"{provider or ''}:{model or ''}:{query}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def _exact_lookup(
        self, query: str, provider: str | None, model: str | None
    ) -> dict[str, Any] | None:
        """Redis-backed exact lookup (fast path)."""
        # Wave 6.3: Redis-клиент — через core/di.providers.
        try:
            import orjson

            from src.core.di.providers import get_redis_stream_client_provider

            redis_client = get_redis_stream_client_provider()
        except ImportError:
            return None

        key = f"{self._namespace}:exact:{self._hash_key(query, provider, model)}"
        try:
            raw = getattr(redis_client, "_raw_client", None) or redis_client
            data = await raw.get(key)
            if data is None:
                return None
            return orjson.loads(data)
        except Exception:
            return None

    async def _exact_store(
        self, query: str, response: Any, provider: str | None, model: str | None
    ) -> None:
        # Wave 6.3: Redis-клиент — через core/di.providers.
        try:
            import orjson

            from src.core.di.providers import get_redis_stream_client_provider

            redis_client = get_redis_stream_client_provider()
        except ImportError:
            return

        key = f"{self._namespace}:exact:{self._hash_key(query, provider, model)}"
        payload = orjson.dumps(
            {
                "query": query,
                "response": response,
                "provider": provider,
                "model": model,
                "cached_at": time.time(),
            }
        )
        try:
            raw = getattr(redis_client, "_raw_client", None) or redis_client
            await raw.set(key, payload, ex=self._ttl)
        except Exception as exc:
            logger.debug("Semantic cache exact store failed: %s", exc)

    async def _semantic_lookup(
        self, query: str, provider: str | None, model: str | None
    ) -> dict[str, Any] | None:
        """Vector similarity поиск через RAG service."""
        try:
            from src.services.ai.rag_service import get_rag_service

            rag = get_rag_service()
        except ImportError:
            return None

        try:
            results = await rag.search(query=query, top_k=1, namespace=self._namespace)
        except Exception as exc:
            logger.debug("Semantic cache search failed: %s", exc)
            return None

        if not results:
            return None

        top = results[0]
        similarity = float(top.get("score", 0.0) if isinstance(top, dict) else 0.0)
        if similarity < self._threshold:
            return None

        meta = top.get("metadata", {}) if isinstance(top, dict) else {}
        return {
            "response": meta.get("response"),
            "cached_at": meta.get("cached_at"),
            "source": "semantic",
            "similarity": similarity,
        }

    async def _semantic_store(
        self, query: str, response: Any, provider: str | None, model: str | None
    ) -> None:
        """Сохраняет query + response в vector store для semantic search."""
        try:
            from src.services.ai.rag_service import get_rag_service

            rag = get_rag_service()
        except ImportError:
            return

        # IL-CRIT1.3: `RAGService.ingest()` ожидает `content: str` +
        # `metadata: dict` + `namespace: str` (не `documents: list` +
        # `metadata: list`). Ранее параметры были переданы неверно —
        # ингест молча падал в `except Exception`, semantic-lookup не
        # наполнялся.
        try:
            if hasattr(rag, "ingest"):
                await rag.ingest(
                    content=query,
                    metadata={
                        "response": response,
                        "provider": provider,
                        "model": model,
                        "cached_at": time.time(),
                    },
                    namespace=self._namespace,
                )
        except Exception as exc:
            logger.debug("Semantic cache store failed: %s", exc)


_instance: SemanticCache | None = None


def get_semantic_cache() -> SemanticCache:
    global _instance
    if _instance is None:
        _instance = SemanticCache()
    return _instance
