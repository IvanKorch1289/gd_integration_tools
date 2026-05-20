"""A/B router для прогрессивной миграции embedding-моделей (Sprint 11 K4 W8).

Routing рассчитывается по hash(query) % 100 vs threshold (=embedding_v2_traffic).
При threshold=0 — весь трафик в v1 (rollback-safe); 100 — весь в v2.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

__all__ = ("EmbeddingABRouter", "EmbeddingMigrationStatus", "EmbeddingVersion")

EmbeddingVersion = Literal["v1", "v2"]


@dataclass(frozen=True, slots=True)
class EmbeddingMigrationStatus:
    """Снапшот состояния миграции для admin endpoint."""

    primary_collection: str
    secondary_collection: str
    traffic_percent: int  # 0..100
    feature_enabled: bool


class EmbeddingABRouter:
    """Решает, какой embedding-вариант использовать для конкретного query.

    Args:
        primary_collection: Имя collection v1 (``docs_bge_m3``).
        secondary_collection: Имя collection v2 (``docs_bge_m3_v2``).
    """

    def __init__(
        self,
        primary_collection: str = "docs_bge_m3",
        secondary_collection: str = "docs_bge_m3_v2",
    ) -> None:
        self._primary = primary_collection
        self._secondary = secondary_collection

    @staticmethod
    def _hash_percent(query: str) -> int:
        """Стабильный хеш query в диапазоне [0..99]."""
        digest = hashlib.sha256(query.encode("utf-8")).digest()
        return digest[0] % 100  # uniform на 256 буцкетов → 100 mod

    def route(self, query: str) -> tuple[EmbeddingVersion, str]:
        """Вернуть (версия, collection) для query.

        Использует ``feature_flags.embedding_ab_migration`` (мастер-switch)
        и ``feature_flags.embedding_v2_traffic`` (0..100 процент).
        """
        from src.backend.core.config.features import feature_flags

        if not feature_flags.embedding_ab_migration:
            return "v1", self._primary

        traffic = max(0, min(100, int(feature_flags.embedding_v2_traffic or 0)))
        if traffic <= 0:
            return "v1", self._primary
        if traffic >= 100:
            return "v2", self._secondary

        bucket = self._hash_percent(query)
        if bucket < traffic:
            return "v2", self._secondary
        return "v1", self._primary

    def status(self) -> EmbeddingMigrationStatus:
        """Сводка для admin REST/dashboard."""
        from src.backend.core.config.features import feature_flags

        return EmbeddingMigrationStatus(
            primary_collection=self._primary,
            secondary_collection=self._secondary,
            traffic_percent=int(feature_flags.embedding_v2_traffic or 0),
            feature_enabled=bool(feature_flags.embedding_ab_migration),
        )
