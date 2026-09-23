"""Privacy lifecycle orchestrator (Sprint 1 — audit 2026-09-22 P1).

Public API:
- :class:`DeleteDataSubject` — main orchestrator
- :class:`ErasureStrategy` — hard_delete vs anonymize
- :class:`ErasureResultStatus` — per-adapter status
- Adapters: PostgreSQL, Redis, S3, Qdrant, LangMem
"""

from __future__ import annotations

from src.backend.core.privacy.delete_data_subject import (
    AdapterResult,
    DeleteDataSubject,
    ErasureAdapter,
    ErasureResultStatus,
    ErasureStrategy,
    LangMemErasureAdapter,
    OrchestratorResult,
    PostgresErasureAdapter,
    QdrantErasureAdapter,
    RedisErasureAdapter,
    S3ErasureAdapter,
    TombstonePublisher,
)

__all__ = (
    "AdapterResult",
    "DeleteDataSubject",
    "ErasureAdapter",
    "ErasureResultStatus",
    "ErasureStrategy",
    "LangMemErasureAdapter",
    "OrchestratorResult",
    "PostgresErasureAdapter",
    "QdrantErasureAdapter",
    "RedisErasureAdapter",
    "S3ErasureAdapter",
    "TombstonePublisher",
)
