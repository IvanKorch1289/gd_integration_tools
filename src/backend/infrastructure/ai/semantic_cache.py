"""Semantic cache — lookup по embedding similarity (cosine).

Cache-hit при семантически близком запросе экономит токены. При
первом miss — embedding считается и кладётся в cache (Redis/Qdrant).
Scaffold-уровень: минимальный интерфейс, конкретный backend
подключается в D3.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

__all__ = ("SemanticCache",)

logger = logging.getLogger("ai.semantic_cache")


@dataclass(slots=True)
class SemanticCache:
    """Простая обёртка над Redis KV (строгий exact-match по хешу)
    с расчётом на будущий Qdrant-semantic-lookup.

    Attrs:
        threshold: порог similarity (cosine) для вторичного semantic-
            lookup; 1.0 = exact-match, 0.85 = similar.
        ttl_seconds: TTL entry в кеше.
    """

    prefix: str = "ai-cache:"
    threshold: float = 0.95
    ttl_seconds: int = 3600

    async def get(self, query: str) -> Any | None:
        try:
            from src.backend.infrastructure.clients.storage.redis import redis_client
        except ImportError:
            return None
        key = self._exact_key(query)
        raw = getattr(redis_client, "_raw_client", None) or redis_client
        try:
            v = await raw.get(key)
            return v
        except Exception as exc:
            logger.debug("SemanticCache get fail: %s", exc)
            return None

    async def set(self, query: str, value: str) -> None:
        try:
            from src.backend.infrastructure.clients.storage.redis import redis_client
        except ImportError:
            return
        key = self._exact_key(query)
        raw = getattr(redis_client, "_raw_client", None) or redis_client
        try:
            await raw.set(key, value, ex=self.ttl_seconds)
        except Exception as exc:
            logger.debug("SemanticCache set fail: %s", exc)

    def _exact_key(self, query: str) -> str:
        h = hashlib.sha256(query.encode("utf-8")).hexdigest()
        return f"{self.prefix}{h}"
