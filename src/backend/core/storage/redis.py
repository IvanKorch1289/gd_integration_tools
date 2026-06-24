"""Capability-checked facade для Redis client (S123 W1).

ADR-0207: services/* (rag_ingest_store, sources/lifecycle, billing/quotas)
импортируют ``get_redis_client`` из ``infrastructure.clients.storage.redis``.
Этот facade переносит публичную поверхность в ``core.storage.redis``.

Migration path:
- ``from src.backend.infrastructure.clients.storage.redis import get_redis_client``
  → ``from src.backend.core.storage.redis import get_redis_client``
"""

from __future__ import annotations

from src.backend.core.di.providers.infrastructure_facade import (  # noqa: F401
    get_redis_client_class as _get_redis_client_cls,
    get_redis_client_factory as _get_redis_client_fn,
)
RedisClient = _get_redis_client_cls()
get_redis_client = _get_redis_client_fn()

__all__ = ("RedisClient", "get_redis_client")
