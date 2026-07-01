from __future__ import annotations

from src.backend.services.ai.semantic_cache.l3_cache import L3RetrievalGraphCache
from src.backend.services.ai.semantic_cache.semantic_cache import SemanticCache

#: Redis pub/sub канал для cross-instance invalidation L3-кеша.
RAG_CACHE_INVALIDATE_CHANNEL = "rag-cache-invalidate"

_instance: SemanticCache | None = None
_l3_instance: L3RetrievalGraphCache | None = None


def get_semantic_cache() -> SemanticCache:
    """Фабрика: singleton SemanticCache."""
    global _instance
    if _instance is None:
        _instance = SemanticCache()
    return _instance


def get_l3_retrieval_cache() -> L3RetrievalGraphCache:
    """Возвращает singleton L3RetrievalGraphCache (lazy-init)."""
    global _l3_instance
    if _l3_instance is None:
        _l3_instance = L3RetrievalGraphCache()
    return _l3_instance
