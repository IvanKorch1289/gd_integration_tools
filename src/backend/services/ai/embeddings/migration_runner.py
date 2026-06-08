"""Batch-индексация в parallel collection (Sprint 11 K4 W8).

Читает чанки из текущего store (v1) и переиндексирует в новую коллекцию
(v2) с использованием нового embedder. Старая коллекция не модифицируется —
позволяет безболезненный rollback через ``embedding_v2_traffic=0``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("EmbeddingMigrationRunner", "MigrationProgress")

logger = get_logger("services.ai.embeddings.migration")


@dataclass(slots=True)
class MigrationProgress:
    """Snapshot текущего прогресса миграции."""

    total: int = 0
    indexed: int = 0
    failed: int = 0
    batches_done: int = 0


class EmbeddingMigrationRunner:
    """Запуск batch-индексации в alt-коллекцию.

    Args:
        source_store: backend с методом ``async list_chunks(collection)``.
        target_store: backend с методом ``async upsert(collection, doc)``.
        embedder: объект с ``async embed(texts: list[str]) -> list[list[float]]``.
        batch_size: размер одного batch'а (default 1000).
    """

    def __init__(
        self,
        source_store: Any,
        target_store: Any,
        embedder: Any,
        *,
        batch_size: int = 1000,
    ) -> None:
        self._source = source_store
        self._target = target_store
        self._embedder = embedder
        self._batch_size = batch_size
        self.progress = MigrationProgress()

    async def run(
        self, *, source_collection: str, target_collection: str
    ) -> MigrationProgress:
        """Запустить миграцию. Идемпотентна: upsert по id."""
        items = await self._source.list_chunks(source_collection)
        self.progress.total = len(items)

        for batch_start in range(0, len(items), self._batch_size):
            batch = items[batch_start : batch_start + self._batch_size]
            texts = [str(it.get("content") or "") for it in batch]
            try:
                vectors = await self._embedder.embed(texts)
            except Exception as exc:
                logger.warning("embed batch %d failed: %s", batch_start, exc)
                self.progress.failed += len(batch)
                continue

            for item, vector in zip(batch, vectors, strict=False):
                try:
                    await self._target.upsert(
                        target_collection,
                        {
                            "id": item.get("id"),
                            "content": item.get("content"),
                            "embedding": vector,
                            "metadata": item.get("metadata"),
                        },
                    )
                    self.progress.indexed += 1
                except Exception as exc:
                    logger.warning("upsert failed: %s", exc)
                    self.progress.failed += 1

            self.progress.batches_done += 1
            await asyncio.sleep(0)  # yield для других tasks

        return self.progress
