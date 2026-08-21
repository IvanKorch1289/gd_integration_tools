"""Sprint 38: storage facade — re-exports infrastructure.clients.storage.

Ponytail fix: services/* импортируют через core.api.storage
(not infrastructure.clients.storage directly).
"""
from __future__ import annotations

# Re-exports infrastructure.clients.storage (3+ violations)
from src.backend.infrastructure.clients.storage import clickhouse
from src.backend.infrastructure.clients.storage import redis as _redis

Clickhouse = clickhouse

__all__ = [
    "clickhouse",
    "_redis",
    "Clickhouse",
]
