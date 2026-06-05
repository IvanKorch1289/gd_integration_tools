# ruff: noqa: S101
"""Unit tests for RagReindexService (services/ai/rag_reindex.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.ai.rag_reindex import (
    RagReindexService,
    ReindexReport,
    get_rag_reindex_service,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    import src.backend.services.ai.rag_reindex as _mod

    _mod._singleton = None
    yield
    _mod._singleton = None


@pytest.fixture()
def service() -> RagReindexService:
    return RagReindexService()


# ── ReindexReport ───────────────────────────────────────────────

def test_reindex_report_to_dict() -> None:
    report = ReindexReport(
        namespace="docs",
        current_fingerprint="abc",
        total_scanned=10,
        stale=2,
        stale_doc_ids=["d1", "d2"],
    )
    d = report.to_dict()
    assert d["namespace"] == "docs"
    assert d["stale"] == 2
    assert d["stale_doc_ids"] == ["d1", "d2"]


# ── reindex_namespace with injected rag ─────────────────────────

@pytest.mark.asyncio
async def test_reindex_namespace_no_store_skips(service: RagReindexService) -> None:
    mock_rag = MagicMock()
    mock_rag._store = None
    svc = RagReindexService(rag_service=mock_rag)
    with patch(
        "src.backend.services.ai.rag_ingest_service._chunker_fingerprint", return_value="fp1"
    ):
        report = await svc.reindex_namespace("ns1")
    assert report.namespace == "ns1"
    assert report.current_fingerprint == "fp1"
    assert report.total_scanned == 0


@pytest.mark.asyncio
async def test_reindex_namespace_store_without_scroll_where(service: RagReindexService) -> None:
    mock_rag = MagicMock()
    mock_rag._store = MagicMock()
    del mock_rag._store.scroll_where
    svc = RagReindexService(rag_service=mock_rag)
    with patch(
        "src.backend.services.ai.rag_ingest_service._chunker_fingerprint", return_value="fp1"
    ):
        report = await svc.reindex_namespace("ns1")
    assert report.total_scanned == 0


@pytest.mark.asyncio
async def test_reindex_namespace_detects_stale(service: RagReindexService) -> None:
    mock_store = AsyncMock()
    mock_store.scroll_where.return_value = [
        {"metadata": {"chunker_fingerprint": "old", "doc_id": "d1"}},
        {"metadata": {"chunker_fingerprint": "fp1", "doc_id": "d2"}},
        {"metadata": {"chunker_fingerprint": "old", "doc_id": "d1"}},  # duplicate
    ]
    mock_rag = MagicMock()
    mock_rag._store = mock_store
    svc = RagReindexService(rag_service=mock_rag)
    with patch(
        "src.backend.services.ai.rag_ingest_service._chunker_fingerprint", return_value="fp1"
    ):
        report = await svc.reindex_namespace("ns1")
    assert report.total_scanned == 3
    assert report.stale == 1
    assert report.stale_doc_ids == ["d1"]


@pytest.mark.asyncio
async def test_reindex_namespace_ignores_missing_metadata(service: RagReindexService) -> None:
    mock_store = AsyncMock()
    mock_store.scroll_where.return_value = [
        {"metadata": None},
        "not_a_dict",
        {"metadata": {"chunker_fingerprint": "old", "doc_id": "d1"}},
    ]
    mock_rag = MagicMock()
    mock_rag._store = mock_store
    svc = RagReindexService(rag_service=mock_rag)
    with patch(
        "src.backend.services.ai.rag_ingest_service._chunker_fingerprint", return_value="fp1"
    ):
        report = await svc.reindex_namespace("ns1")
    assert report.total_scanned == 3
    assert report.stale == 1


@pytest.mark.asyncio
async def test_reindex_namespace_scroll_where_raises(service: RagReindexService) -> None:
    mock_store = AsyncMock()
    mock_store.scroll_where.side_effect = RuntimeError("db down")
    mock_rag = MagicMock()
    mock_rag._store = mock_store
    svc = RagReindexService(rag_service=mock_rag)
    with patch(
        "src.backend.services.ai.rag_ingest_service._chunker_fingerprint", return_value="fp1"
    ):
        report = await svc.reindex_namespace("ns1")
    assert report.total_scanned == 0


@pytest.mark.asyncio
async def test_reindex_namespace_uses_provided_hash(service: RagReindexService) -> None:
    mock_store = AsyncMock()
    mock_store.scroll_where.return_value = []
    mock_rag = MagicMock()
    mock_rag._store = mock_store
    svc = RagReindexService(rag_service=mock_rag)
    report = await svc.reindex_namespace("ns1", since_chunker_hash="custom")
    assert report.current_fingerprint == "custom"


# ── _ensure_rag via app state ───────────────────────────────────

@pytest.mark.asyncio
async def test_ensure_rag_from_app_state() -> None:
    mock_rag = MagicMock()
    mock_app = MagicMock()
    mock_app.state.rag_service = mock_rag
    with patch(
        "src.backend.core.di.app_state.get_app_ref", return_value=mock_app
    ):
        svc = RagReindexService()
        rag = svc._ensure_rag()
        assert rag is mock_rag


def test_ensure_rag_raises_when_missing() -> None:
    with patch(
        "src.backend.core.di.app_state.get_app_ref", return_value=None
    ):
        svc = RagReindexService()
        with pytest.raises(RuntimeError, match="rag_service не зарегистрирован"):
            svc._ensure_rag()


# ── singleton ───────────────────────────────────────────────────

def test_get_rag_reindex_service_singleton() -> None:
    s1 = get_rag_reindex_service()
    s2 = get_rag_reindex_service()
    assert s1 is s2
