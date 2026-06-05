"""Тесты ConsolidationEngine (Wave D.6)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.memory.langmem.consolidation import (
    ConsolidationEngine,
    _cluster_by_session,
    _parse_facts,
)


@pytest.mark.asyncio
async def test_cluster_by_session() -> None:
    episodes = [
        {"tenant": "t1", "session_id": "s1", "content": "a"},
        {"tenant": "t1", "session_id": "s1", "content": "b"},
        {"tenant": "t1", "session_id": "s2", "content": "c"},
    ]
    clusters = _cluster_by_session(episodes)
    assert len(clusters) == 2
    assert len(clusters[("t1", "s1")]) == 2


def test_parse_facts_extracts_confidence() -> None:
    text = '[{"fact":"Иван любит чай","confidence":0.9},{"fact":"x","confidence":0.4}]'
    facts = _parse_facts(text)
    assert len(facts) == 2
    assert facts[0].text == "Иван любит чай"
    assert facts[0].confidence == 0.9


def test_parse_facts_empty_on_invalid_json() -> None:
    assert _parse_facts("not-json") == []
    assert _parse_facts("") == []


@pytest.mark.asyncio
async def test_run_processes_clusters_above_threshold() -> None:
    langmem = type("L", (), {})()
    langmem.recall = AsyncMock(
        return_value=[
            {"tenant": "t1", "session_id": "s1", "role": "user", "content": "Hi"},
            {
                "tenant": "t1",
                "session_id": "s1",
                "role": "assistant",
                "content": "Hello",
            },
            {"tenant": "t1", "session_id": "s1", "role": "user", "content": "Bye"},
        ]
    )
    langmem.add_semantic = AsyncMock(return_value="pid")

    gateway = type("G", (), {})()
    gateway.acompletion = AsyncMock(
        return_value={
            "choices": [
                {"message": {"content": '[{"fact":"User said hi","confidence":0.9}]'}}
            ]
        }
    )

    engine = ConsolidationEngine(langmem_service=langmem, gateway=gateway)
    report = await engine.run(batch_size=10)
    assert report.processed == 3
    assert report.clusters == 1
    assert report.facts_extracted == 1
    assert report.facts_persisted == 1
    langmem.add_semantic.assert_awaited()


@pytest.mark.asyncio
async def test_run_skips_small_clusters() -> None:
    langmem = type("L", (), {})()
    langmem.recall = AsyncMock(
        return_value=[
            {"tenant": "t1", "session_id": "s1", "role": "user", "content": "Hi"}
        ]
    )
    langmem.add_semantic = AsyncMock(return_value="pid")
    gateway = type("G", (), {})()
    gateway.acompletion = AsyncMock(return_value={})

    engine = ConsolidationEngine(langmem_service=langmem, gateway=gateway)
    report = await engine.run(batch_size=10)
    assert report.skipped_clusters == 1
    assert report.facts_persisted == 0
