"""Unit-тесты RagQueryStatsCollector + RagCachePrewarmer (S13 K4 W1)."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.rag_cache_prewarmer import RagCachePrewarmer
from src.backend.services.ai.rag_query_stats import RagQueryStatsCollector


@pytest.mark.asyncio
async def test_stats_collector_in_memory() -> None:
    collector = RagQueryStatsCollector()
    await collector.record("t1", "what is python?")
    await collector.record("t1", "what is python?")
    await collector.record("t1", "what is rust?")
    await collector.record("t2", "what is go?")

    top = await collector.top_queries("t1", n=10)
    assert len(top) == 2
    queries = [q for q, _ in top]
    assert "what is python?" in queries
    assert "what is rust?" in queries
    # Топ для t1 не пересекается с t2.
    top_t2 = await collector.top_queries("t2", n=10)
    assert len(top_t2) == 1
    assert top_t2[0][0] == "what is go?"


@pytest.mark.asyncio
async def test_stats_empty_query_skipped() -> None:
    collector = RagQueryStatsCollector()
    await collector.record("t1", "")
    top = await collector.top_queries("t1", n=10)
    assert top == []


@pytest.mark.asyncio
async def test_prewarmer_loads_top_queries() -> None:
    stats = RagQueryStatsCollector()
    await stats.record("t1", "q1")
    await stats.record("t1", "q1")
    await stats.record("t1", "q2")

    rag = AsyncMock()
    rag.query = AsyncMock(return_value={"answer": "x"})

    prewarmer = RagCachePrewarmer(
        rag_service=rag, stats_collector=stats, top_n=10, throttle_ms=0
    )
    loaded = await prewarmer.prewarm_tenant("t1")
    assert loaded == 2
    # 2 уникальных query → 2 вызова rag.query.
    assert rag.query.await_count == 2


@pytest.mark.asyncio
async def test_prewarmer_handles_query_exception() -> None:
    stats = RagQueryStatsCollector()
    await stats.record("t1", "q1")

    rag = AsyncMock()
    rag.query = AsyncMock(side_effect=RuntimeError("qdrant down"))

    prewarmer = RagCachePrewarmer(
        rag_service=rag, stats_collector=stats, top_n=10, throttle_ms=0
    )
    loaded = await prewarmer.prewarm_tenant("t1")
    # Exception не приостанавливает работу, но `loaded` всё равно 0
    # т.к. TypeError fallback в `query` тоже падает.
    assert loaded == 0


@pytest.mark.asyncio
async def test_prewarm_all_tenants() -> None:
    stats = RagQueryStatsCollector()
    await stats.record("t1", "q1")
    await stats.record("t2", "q2")

    rag = AsyncMock()
    rag.query = AsyncMock(return_value={"answer": "x"})

    prewarmer = RagCachePrewarmer(
        rag_service=rag, stats_collector=stats, top_n=10, throttle_ms=0
    )
    results = await prewarmer.prewarm_all_tenants(["t1", "t2"])
    assert results == {"t1": 1, "t2": 1}
