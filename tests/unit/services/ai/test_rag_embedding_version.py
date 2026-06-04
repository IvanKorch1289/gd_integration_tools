"""Unit test для Block 3.5 (gap-ai-3.5, ADR-0074).

Проверяет:

1. ``RagIngestService`` добавляет ``embedding_provider``, ``embedding_model``,
   ``chunker_fingerprint_version`` в ``chunk.metadata``.
2. ``_filter_by_embedding_version`` в non-strict mode пропускает chunks с
   mismatch (counter inc).
3. ``embedding_strict_mode=True`` фильтрует chunks с mismatch.
4. chunks без ``embedding_model`` (legacy) — пропускаются без strict-фильтра.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_ingest_includes_embedding_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RagIngestService пишет embedding_provider/model + fingerprint в metadata."""
    from src.backend.core.config import rag
    from src.backend.services.ai.rag_ingest_service import RagIngestService

    monkeypatch.setattr(
        rag.rag_settings, "embedding_provider", "sentence-transformers", raising=True
    )
    monkeypatch.setattr(
        rag.rag_settings, "embedding_model", "BAAI/bge-m3", raising=True
    )

    rag_mock = AsyncMock()
    rag_mock.ingest = AsyncMock(return_value="doc-1")
    svc = RagIngestService(rag_service=rag_mock)

    await svc.ingest([("file.txt", b"content")], collection="ns")
    call = rag_mock.ingest.await_args
    assert call is not None
    metadata = call.kwargs["metadata"]
    assert metadata["embedding_provider"] == "sentence-transformers"
    assert metadata["embedding_model"] == "BAAI/bge-m3"
    assert "chunker_fingerprint_version" in metadata
    assert isinstance(metadata["chunker_fingerprint_version"], int)


def test_filter_passes_chunks_with_matching_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """chunk.metadata.embedding_model == current → пропускается."""
    from src.backend.core.config import rag
    from src.backend.services.ai.rag_service import _filter_by_embedding_version

    monkeypatch.setattr(
        rag.rag_settings, "embedding_model", "BAAI/bge-m3", raising=True
    )
    chunks: list[dict[str, Any]] = [
        {"id": "1", "metadata": {"embedding_model": "BAAI/bge-m3"}},
        {"id": "2", "metadata": {"embedding_model": "BAAI/bge-m3"}},
    ]
    filtered = _filter_by_embedding_version(chunks)
    assert len(filtered) == 2


def test_filter_drops_mismatch_in_strict_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """strict_mode=True + mismatch → chunk отфильтрован."""
    from src.backend.core.config import rag
    from src.backend.services.ai.rag_service import _filter_by_embedding_version

    monkeypatch.setattr(
        rag.rag_settings, "embedding_model", "BAAI/bge-m3", raising=True
    )
    monkeypatch.setattr(rag.rag_settings, "embedding_strict_mode", True, raising=True)
    chunks: list[dict[str, Any]] = [
        {"id": "1", "metadata": {"embedding_model": "BAAI/bge-m3"}},
        {"id": "2", "metadata": {"embedding_model": "old-model-v1"}},
    ]
    filtered = _filter_by_embedding_version(chunks)
    assert len(filtered) == 1
    assert filtered[0]["id"] == "1"


def test_filter_keeps_mismatch_in_warn_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """strict_mode=False + mismatch → chunk проходит + counter inc (warn-only)."""
    from src.backend.core.config import rag
    from src.backend.services.ai.rag_service import _filter_by_embedding_version

    monkeypatch.setattr(
        rag.rag_settings, "embedding_model", "BAAI/bge-m3", raising=True
    )
    monkeypatch.setattr(rag.rag_settings, "embedding_strict_mode", False, raising=True)
    chunks: list[dict[str, Any]] = [
        {"id": "1", "metadata": {"embedding_model": "old-model-v1"}}
    ]
    filtered = _filter_by_embedding_version(chunks)
    assert len(filtered) == 1


def test_filter_passes_legacy_chunks_without_embedding_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """chunks без embedding_model в metadata (legacy) → пропускаются."""
    from src.backend.core.config import rag
    from src.backend.services.ai.rag_service import _filter_by_embedding_version

    monkeypatch.setattr(
        rag.rag_settings, "embedding_model", "BAAI/bge-m3", raising=True
    )
    monkeypatch.setattr(rag.rag_settings, "embedding_strict_mode", True, raising=True)
    chunks: list[dict[str, Any]] = [
        {"id": "1", "metadata": {}},  # legacy без provenance
        {"id": "2", "metadata": {"embedding_model": "BAAI/bge-m3"}},
    ]
    filtered = _filter_by_embedding_version(chunks)
    assert len(filtered) == 2  # legacy не отфильтровываются даже в strict
