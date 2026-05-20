"""Тесты Sprint 11 K4 W8 — EmbeddingABRouter + EmbeddingMigrationRunner."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.embeddings.ab_migration import EmbeddingABRouter
from src.backend.services.ai.embeddings.migration_runner import (
    EmbeddingMigrationRunner,
    MigrationProgress,
)


@pytest.mark.asyncio
async def test_router_returns_v1_when_feature_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без feature-flag роутер всегда возвращает v1."""
    from src.backend.core.config import features

    monkeypatch.setattr(features.feature_flags, "embedding_ab_migration", False)
    monkeypatch.setattr(features.feature_flags, "embedding_v2_traffic", 50)
    router = EmbeddingABRouter()

    version, collection = router.route("any query")
    assert version == "v1"
    assert collection == "docs_bge_m3"


@pytest.mark.asyncio
async def test_router_returns_v2_when_traffic_100(monkeypatch: pytest.MonkeyPatch) -> None:
    """traffic=100 → весь трафик на v2."""
    from src.backend.core.config import features

    monkeypatch.setattr(features.feature_flags, "embedding_ab_migration", True)
    monkeypatch.setattr(features.feature_flags, "embedding_v2_traffic", 100)
    router = EmbeddingABRouter()

    version, collection = router.route("query")
    assert version == "v2"
    assert collection == "docs_bge_m3_v2"


@pytest.mark.asyncio
async def test_router_splits_traffic_by_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    """traffic=50 → bucket < 50 → v2, иначе v1. Стабильно по hash(query)."""
    from src.backend.core.config import features

    monkeypatch.setattr(features.feature_flags, "embedding_ab_migration", True)
    monkeypatch.setattr(features.feature_flags, "embedding_v2_traffic", 50)
    router = EmbeddingABRouter()

    # Запустим 200 запросов и проверим, что обе версии присутствуют.
    versions = {router.route(f"query-{i}")[0] for i in range(200)}
    assert versions == {"v1", "v2"}


@pytest.mark.asyncio
async def test_router_status_includes_traffic(monkeypatch: pytest.MonkeyPatch) -> None:
    """status() возвращает текущий traffic и feature-flag."""
    from src.backend.core.config import features

    monkeypatch.setattr(features.feature_flags, "embedding_ab_migration", True)
    monkeypatch.setattr(features.feature_flags, "embedding_v2_traffic", 25)
    router = EmbeddingABRouter()

    status = router.status()
    assert status.traffic_percent == 25
    assert status.feature_enabled is True
    assert status.primary_collection == "docs_bge_m3"
    assert status.secondary_collection == "docs_bge_m3_v2"


@pytest.mark.asyncio
async def test_migration_runner_indexes_all_chunks() -> None:
    """run() обрабатывает все чанки и формирует прогресс."""
    source = AsyncMock()
    source.list_chunks = AsyncMock(
        return_value=[
            {"id": "1", "content": "doc1", "metadata": {}},
            {"id": "2", "content": "doc2", "metadata": {}},
            {"id": "3", "content": "doc3", "metadata": {}},
        ]
    )
    target = AsyncMock()
    target.upsert = AsyncMock(return_value=None)
    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[[0.1], [0.2], [0.3]])
    runner = EmbeddingMigrationRunner(source, target, embedder, batch_size=10)

    progress = await runner.run(
        source_collection="docs_bge_m3", target_collection="docs_bge_m3_v2"
    )

    assert isinstance(progress, MigrationProgress)
    assert progress.total == 3
    assert progress.indexed == 3
    assert progress.failed == 0
    assert progress.batches_done == 1
