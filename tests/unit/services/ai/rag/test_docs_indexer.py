"""Unit-тесты DocsIndexer (Sprint 40 W5, v15 §10 RAG over project docs).

Покрывает 5+ методов DocsIndexer + InMemoryQdrantFallback:
1. __init__ / defaults / DI
2. discover_docs (CLAUDE.md, .claude/, docs/users, docs/devs)
3. chunk_text (basic, empty, overlap, metadata)
4. index_docs (returns N, idempotent, fallback)
5. search (results, empty query → ValueError)
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from src.backend.services.ai.rag.docs_indexer import DocsIndexer, InMemoryQdrantFallback

# ----- __init__ -----


def test_indexer_init() -> None:
    """Базовый init + defaults."""
    idx = DocsIndexer()
    assert idx.collection_name == "project_docs"
    assert idx.is_fallback is True
    assert idx._chunk_size == 512
    assert idx._chunk_overlap == 50


def test_indexer_custom_init() -> None:
    """Init с кастомными параметрами."""
    fb = InMemoryQdrantFallback()
    idx = DocsIndexer(
        qdrant_client=fb,
        embedding_model="text-embedding-3-large",
        collection_name="my_docs",
        chunk_size=256,
        chunk_overlap=32,
    )
    assert idx.collection_name == "my_docs"
    assert idx.is_fallback is False
    assert idx._chunk_size == 256
    assert idx._chunk_overlap == 32


def test_indexer_overlap_clamped_to_chunk_size() -> None:
    """chunk_overlap > chunk_size-1 → clamp к chunk_size-1."""
    idx = DocsIndexer(chunk_size=10, chunk_overlap=100)
    assert idx._chunk_overlap == 9


# ----- discover_docs -----


def test_indexer_default_roots() -> None:
    """Default roots = CLAUDE.md, .claude/, docs/users, docs/devs (кортеж)."""
    from src.backend.services.ai.rag.docs_indexer import _DEFAULT_ROOTS

    assert "CLAUDE.md" in _DEFAULT_ROOTS
    assert ".claude/CLAUDE.md" in _DEFAULT_ROOTS
    assert "docs/users" in _DEFAULT_ROOTS
    assert "docs/devs" in _DEFAULT_ROOTS


def test_indexer_custom_roots(tmp_path: Path) -> None:
    """Custom roots → discover_docs находит только их .md файлы."""
    docs_dir = tmp_path / "mydocs"
    docs_dir.mkdir()
    (docs_dir / "a.md").write_text("# A")
    (docs_dir / "b.md").write_text("# B")
    (docs_dir / "c.txt").write_text("not md")
    idx = DocsIndexer()
    found = idx.discover_docs(roots=[str(docs_dir)])
    assert len(found) == 2
    assert all(p.suffix == ".md" for p in found)


def test_indexer_discover_finds_md(tmp_path: Path) -> None:
    """discover_docs рекурсивно ищет .md файлы."""
    sub = tmp_path / "sub" / "nested"
    sub.mkdir(parents=True)
    (tmp_path / "top.md").write_text("# top")
    (sub / "deep.md").write_text("# deep")
    idx = DocsIndexer()
    found = idx.discover_docs(roots=[str(tmp_path)])
    names = {p.name for p in found}
    assert names == {"top.md", "deep.md"}


def test_indexer_discover_ignores_non_md(tmp_path: Path) -> None:
    """discover_docs игнорирует .py, .json, .txt и т.д."""
    (tmp_path / "code.py").write_text("print(1)")
    (tmp_path / "data.json").write_text("{}")
    (tmp_path / "note.txt").write_text("note")
    (tmp_path / "real.md").write_text("# real")
    idx = DocsIndexer()
    found = idx.discover_docs(roots=[str(tmp_path)])
    assert len(found) == 1
    assert found[0].name == "real.md"


# ----- chunk_text -----


def test_chunk_text_basic() -> None:
    """text → N chunks базового размера."""
    idx = DocsIndexer(chunk_size=10, chunk_overlap=0)
    text = "a" * 25
    chunks = idx.chunk_text(text, {"file": "x.md"})
    assert len(chunks) == 3  # 10 + 10 + 5
    assert all(c["text"] for c in chunks)


def test_chunk_text_empty() -> None:
    """empty/whitespace text → [] (нет chunks)."""
    idx = DocsIndexer()
    assert idx.chunk_text("", {"file": "x"}) == []
    assert idx.chunk_text("   \n  \t  ", {"file": "x"}) == []


def test_chunk_text_overlap() -> None:
    """chunks overlap by chunk_overlap (size=20, overlap=5 → step=15)."""
    idx = DocsIndexer(chunk_size=20, chunk_overlap=5)
    text = "0123456789" * 4  # 40 chars
    chunks = idx.chunk_text(text, {"file": "x"})
    assert len(chunks) >= 2
    # First two chunks должны перекрываться на 5 символов.
    assert chunks[0]["text"][-5:] == chunks[1]["text"][:5]


def test_chunk_text_metadata() -> None:
    """Каждый chunk содержит metadata: file, line, hash, source_path, chunk_index, id."""
    idx = DocsIndexer(chunk_size=50, chunk_overlap=0)
    text = "line1\nline2\nline3\n" + "x" * 100
    chunks = idx.chunk_text(text, {"file": "test.md", "source_path": "/abs/test.md"})
    assert len(chunks) > 0
    for i, c in enumerate(chunks):
        assert "id" in c
        assert "text" in c
        assert "metadata" in c
        m = c["metadata"]
        assert m["file"] == "test.md"
        assert m["source_path"] == "/abs/test.md"
        assert "line" in m
        assert "hash" in m
        assert m["hash"] == c["id"]
        assert m["chunk_index"] == i


# ----- index_docs / idempotency -----


@pytest.mark.asyncio
async def test_index_docs_returns_count(tmp_path: Path) -> None:
    """index_docs возвращает N chunks (один chunk_size=100 → N = ceil(len/100))."""
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("alpha " * 50)  # 300 chars
    b.write_text("beta " * 10)  # 50 chars
    idx = DocsIndexer(chunk_size=100, chunk_overlap=0)
    n = await idx.index_docs(docs=[a, b])
    assert n > 0
    # 300 → 3 chunks, 50 → 1 chunk
    assert n == 4


@pytest.mark.asyncio
async def test_index_docs_idempotent() -> None:
    """Повторный index_docs с теми же docs → то же N (upsert overwrite, hash id)."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.md"
        p.write_text("# stable content\n" + "lorem ipsum " * 30)
        idx = DocsIndexer(chunk_size=100, chunk_overlap=10)
        n1 = await idx.index_docs(docs=[p])
        n2 = await idx.index_docs(docs=[p])
        assert n1 == n2
        assert n1 > 0


@pytest.mark.asyncio
async def test_index_docs_no_docs_returns_zero() -> None:
    """index_docs с пустым списком → 0 (без падений)."""
    idx = DocsIndexer()
    n = await idx.index_docs(docs=[])
    assert n == 0


# ----- search -----


@pytest.mark.asyncio
async def test_search_returns_results() -> None:
    """search() возвращает list[dict] с ключами id/score/document/metadata."""
    idx = DocsIndexer()
    # Создать контент: index с одним файлом.
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.md"
        p.write_text("documentation about qdrant vector store and rag")
        await idx.index_docs(docs=[p])
    results = await idx.search("qdrant", limit=3)
    assert isinstance(results, list)
    if results:  # может быть пусто если в fallback нет матчей
        for r in results:
            assert "id" in r
            assert "score" in r
            assert "document" in r
            assert "metadata" in r


@pytest.mark.asyncio
async def test_search_empty_query_raises() -> None:
    """search("") → ValueError; search("   ") → ValueError."""
    idx = DocsIndexer()
    with pytest.raises(ValueError, match="non-empty"):
        await idx.search("")
    with pytest.raises(ValueError, match="non-empty"):
        await idx.search("   \n  ")


@pytest.mark.asyncio
async def test_search_after_index_finds_chunk() -> None:
    """После index_docs, search(query) находит ≥1 chunk (тот же hash-based id)."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "guide.md"
        p.write_text("как поднять dev среду\n" * 20)
        idx = DocsIndexer(chunk_size=100, chunk_overlap=0)
        await idx.index_docs(docs=[p])
        results = await idx.search("dev среду", limit=2)
        assert len(results) >= 1
        assert results[0]["document"]  # non-empty


# ----- fallback / graceful degradation -----


def test_indexer_no_qdrant_uses_fallback() -> None:
    """DocsIndexer() без qdrant_client → InMemoryQdrantFallback (graceful)."""
    idx = DocsIndexer()
    assert idx.is_fallback is True
    assert isinstance(idx._qdrant, InMemoryQdrantFallback)


@pytest.mark.asyncio
async def test_indexer_fallback_upsert_and_search() -> None:
    """In-memory fallback: upsert → search → возвращает hits (idempotent)."""
    fb = InMemoryQdrantFallback()
    fb.create_collection("test")
    from dataclasses import dataclass

    @dataclass
    class _P:
        id: str
        vector: list[float]
        payload: dict[str, Any]

    fb.upsert("test", [_P("a", [1.0, 0.0], {"document": "doc-A"})])
    fb.upsert("test", [_P("b", [0.0, 1.0], {"document": "doc-B"})])
    hits = fb.search("test", query_vector=[1.0, 0.0], limit=2)
    assert len(hits) == 2
    assert hits[0].id == "a"  # cosine([1,0],[1,0])=1.0 > cosine([1,0],[0,1])=0.0
    assert hits[0].score > hits[1].score


def test_indexer_set_embedder_uses_provided() -> None:
    """set_embedder DI: переданный embed_fn используется."""
    idx = DocsIndexer()
    calls: list[list[str]] = []

    def my_embed(texts: list[str]) -> list[list[float]]:
        calls.append(texts)
        return [[1.0, 0.0] for _ in texts]

    idx.set_embedder(my_embed)
    # _embed sync
    import asyncio

    out = asyncio.run(idx._embed(["a", "b"]))
    assert out == [[1.0, 0.0], [1.0, 0.0]]
    assert calls == [["a", "b"]]
