"""Capability-checked facade для Redis client (S123 W1).

ADR-0207: services/* (rag_ingest_store, sources/lifecycle, billing/quotas)
импортируют ``get_redis_client`` из ``infrastructure.clients.storage.redis``.
Этот facade переносит публичную поверхность в ``core.storage.redis``.

Migration path:
- ``from src.backend.infrastructure.clients.storage.redis import get_redis_client``
  → ``from src.backend.core.storage.redis import get_redis_client``
"""

from __future__ import annotations

from src.backend.infrastructure.clients.storage.redis import (  # noqa: F401
    RedisClient,
    get_redis_client,
)

__all__ = ("RedisClient", "get_redis_client")
