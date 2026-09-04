"""Sprint 38: storage facade — re-exports infrastructure.clients.storage.

Ponytail fix: services/* импортируют через core.api.storage
(not infrastructure.clients.storage directly).
"""

from __future__ import annotations

# Re-exports infrastructure.clients.storage (3+ violations)
from src.backend.infrastructure.clients.storage import (
    clickhouse,
    clickhouse_admin_client,
)
from src.backend.infrastructure.clients.storage import redis as _redis

# S170 PONYTAIL: добавлен get_redis_client re-export — некоторые callers
# ходили через core.api.storage.get_redis_client, но facade пустел —
# фикс под mypy errors в authorization/facade.py, workflows/hitl_pubsub.py.
get_redis_client = _redis.get_redis_client

Clickhouse = clickhouse

__all__ = [
    "clickhouse",
    "clickhouse_admin_client",
    "_redis",
    "Clickhouse",
    "get_redis_client",
]
