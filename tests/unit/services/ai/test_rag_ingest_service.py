"""Тесты RagIngestService: inline ingest + status tracking."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.rag_ingest_service import RagIngestService


@pytest.mark.asyncio
async def test_ingest_inline_processes_all_files() -> None:
    rag = type("R", (), {})()
    rag.ingest = AsyncMock(side_effect=["doc1", "doc2"])
    service = RagIngestService(rag_service=rag, deferred=False)

    result = await service.ingest(
        files=[("a.txt", b"hello"), ("b.txt", b"world")],
        collection="docs",
    )
    assert result["status"] == "completed"
    assert result["doc_ids"] == ["doc1", "doc2"]
    assert result["processed"] == 2
    assert rag.ingest.await_count == 2


@pytest.mark.asyncio
async def test_ingest_records_errors() -> None:
    rag = type("R", (), {})()
    rag.ingest = AsyncMock(side_effect=[RuntimeError("boom"), "doc-ok"])
    service = RagIngestService(rag_service=rag, deferred=False)

    result = await service.ingest(
        files=[("bad.txt", b"x"), ("good.txt", b"y")]
    )
    assert result["status"] == "completed_with_errors"
    assert result["doc_ids"] == ["doc-ok"]
    assert result["errors"][0]["file"] == "bad.txt"


@pytest.mark.asyncio
async def test_status_returns_state() -> None:
    rag = type("R", (), {})()
    rag.ingest = AsyncMock(return_value="d")
    service = RagIngestService(rag_service=rag, deferred=False)
    started = await service.ingest(files=[("a.txt", b"x")])
    state = await service.status(started["task_id"])
    assert state is not None and state["status"] == "completed"


@pytest.mark.asyncio
async def test_status_returns_none_for_unknown_id() -> None:
    service = RagIngestService(rag_service=object())
    assert await service.status("missing") is None


@pytest.mark.asyncio
async def test_chunker_fingerprint_propagates_to_metadata() -> None:
    captured: list[dict] = []

    async def _capture(text, metadata=None, namespace="default"):  # noqa: ANN001
        captured.append(metadata or {})
        return "doc"

    rag = type("R", (), {})()
    rag.ingest = _capture
    service = RagIngestService(rag_service=rag, deferred=False)
    await service.ingest(files=[("x.txt", b"x")], collection="c1")
    assert "chunker_fingerprint" in captured[0]
    assert isinstance(captured[0]["chunker_fingerprint"], str)


@pytest.mark.asyncio
async def test_list_recent_returns_newest_first() -> None:
    rag = type("R", (), {})()
    rag.ingest = AsyncMock(return_value="d")
    service = RagIngestService(rag_service=rag, deferred=False)
    await service.ingest(files=[("a.txt", b"x")])
    await service.ingest(files=[("b.txt", b"y")])
    recent = await service.list_recent(limit=10)
    assert len(recent) == 2
    assert recent[0]["status"] == "completed"
