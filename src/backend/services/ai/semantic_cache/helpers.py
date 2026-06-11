from __future__ import annotations
import asyncio
import contextlib
import hashlib
import time
from typing import Any

from src.backend.core.logging import get_logger

#: Redis pub/sub канал для cross-instance invalidation L3-кеша.
RAG_CACHE_INVALIDATE_CHANNEL = "rag-cache-invalidate"

def get_semantic_cache() -> SemanticCache:
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

