"""Unit test для Block 3.3 (gap-ai-3.3, ADR-0074).

Проверяет source attribution в RAG augmented prompts:

1. ``source_attribution_enabled=True`` (default) → каждый chunk имеет
   ``[источник: <source>]`` маркер.
2. ``source_attribution_enabled=False`` → passthrough старого формата
   (только document text).
3. Source-id priority: metadata.source > metadata.filename > metadata.doc_id > chunk.id.
"""

from __future__ import annotations

from typing import Any

import pytest


def test_format_includes_source_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """source_attribution_enabled=True → context содержит [источник: ...]."""
    from src.backend.core.config import rag
    from src.backend.services.ai.rag_service import _format_context_with_sources

    monkeypatch.setattr(
        rag.rag_settings, "source_attribution_enabled", True, raising=True
    )
    chunks: list[dict[str, Any]] = [
        {
            "id": "1",
            "document": "Кредитная политика банка...",
            "metadata": {"source": "policy_v3.pdf"},
        },
        {
            "id": "2",
            "document": "Условия овердрафта...",
            "metadata": {"filename": "overdraft_terms.docx"},
        },
    ]
    context = _format_context_with_sources(chunks)
    assert "[источник: policy_v3.pdf]" in context
    assert "[источник: overdraft_terms.docx]" in context
    assert "Кредитная политика банка..." in context


def test_format_passthrough_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """source_attribution_enabled=False → нет маркера, только document."""
    from src.backend.core.config import rag
    from src.backend.services.ai.rag_service import _format_context_with_sources

    monkeypatch.setattr(
        rag.rag_settings, "source_attribution_enabled", False, raising=True
    )
    chunks: list[dict[str, Any]] = [
        {
            "id": "1",
            "document": "Текст документа",
            "metadata": {"source": "policy_v3.pdf"},
        }
    ]
    context = _format_context_with_sources(chunks)
    assert "[источник:" not in context
    assert "Текст документа" in context


def test_source_priority_source_over_filename(monkeypatch: pytest.MonkeyPatch) -> None:
    """Priority: metadata.source > filename > doc_id > id."""
    from src.backend.core.config import rag
    from src.backend.services.ai.rag_service import _extract_source_id

    monkeypatch.setattr(
        rag.rag_settings, "source_attribution_enabled", True, raising=True
    )

    # source explicit wins.
    chunk = {
        "id": "chunk-abc",
        "metadata": {
            "source": "explicit_src",
            "filename": "ignored.pdf",
            "doc_id": "ignored-doc",
        },
    }
    assert _extract_source_id(chunk) == "explicit_src"

    # filename wins без source.
    chunk = {
        "id": "chunk-abc",
        "metadata": {"filename": "fname.pdf", "doc_id": "ignored"},
    }
    assert _extract_source_id(chunk) == "fname.pdf"

    # doc_id wins при отсутствии source/filename.
    chunk = {"id": "chunk-abc", "metadata": {"doc_id": "doc-1"}}
    assert _extract_source_id(chunk) == "doc-1"

    # fallback на chunk.id.
    chunk = {"id": "chunk-xyz", "metadata": {}}
    assert _extract_source_id(chunk) == "chunk-xyz"

    # пустой chunk → empty string.
    chunk = {}
    assert _extract_source_id(chunk) == ""


def test_format_skips_chunks_without_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """chunks без document не попадают в context."""
    from src.backend.core.config import rag
    from src.backend.services.ai.rag_service import _format_context_with_sources

    monkeypatch.setattr(
        rag.rag_settings, "source_attribution_enabled", True, raising=True
    )
    chunks: list[dict[str, Any]] = [
        {"id": "1", "metadata": {"source": "doc.pdf"}},  # без document
        {"id": "2", "document": "Real text", "metadata": {"source": "src2"}},
    ]
    context = _format_context_with_sources(chunks)
    assert "Real text" in context
    assert "doc.pdf" not in context  # первый chunk skipped целиком
    assert "[источник: src2]" in context
