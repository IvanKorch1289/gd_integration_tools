# ruff: noqa: S101
"""Unit-тесты RAG-chunkers (token + recursive)."""

from __future__ import annotations

import pytest

from src.backend.services.ai.chunkers import Chunker, get_chunker
from src.backend.services.ai.chunkers.recursive import RecursiveChunker
from src.backend.services.ai.chunkers.token import TokenChunker


class TestFactory:
    def test_factory_returns_token_chunker(self) -> None:
        c = get_chunker("token", chunk_size=64, chunk_overlap=8)
        assert isinstance(c, TokenChunker)
        assert isinstance(c, Chunker)

    def test_factory_returns_recursive_chunker(self) -> None:
        c = get_chunker("recursive", chunk_size=64, chunk_overlap=8)
        assert isinstance(c, RecursiveChunker)
        assert isinstance(c, Chunker)

    def test_factory_unknown_strategy_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown chunk strategy"):
            get_chunker("unknown", chunk_size=10, chunk_overlap=1)  # type: ignore[arg-type]

    def test_factory_invalid_size(self) -> None:
        with pytest.raises(ValueError, match="chunk_size"):
            get_chunker("token", chunk_size=0, chunk_overlap=0)

    def test_factory_invalid_overlap(self) -> None:
        with pytest.raises(ValueError, match="chunk_overlap"):
            get_chunker("token", chunk_size=10, chunk_overlap=10)


class TestTokenChunker:
    def test_empty_text(self) -> None:
        c = TokenChunker(chunk_size=10, chunk_overlap=2)
        assert c.split("") == []

    def test_small_doc_single_chunk(self) -> None:
        c = TokenChunker(chunk_size=200, chunk_overlap=20)
        text = "Короткий документ"
        out = c.split(text)
        assert len(out) >= 1
        assert "".join(out).startswith("Короткий")

    def test_large_doc_multiple_chunks(self) -> None:
        c = TokenChunker(chunk_size=20, chunk_overlap=4)
        text = "слово " * 200
        out = c.split(text)
        assert len(out) >= 2
        for chunk in out:
            assert chunk


class TestRecursiveChunker:
    def test_empty_text(self) -> None:
        c = RecursiveChunker(chunk_size=20, chunk_overlap=4)
        assert c.split("") == []

    def test_split_paragraphs(self) -> None:
        c = RecursiveChunker(chunk_size=30, chunk_overlap=4)
        text = "Первый абзац.\n\nВторой абзац длиннее.\n\nТретий короткий."
        out = c.split(text)
        assert len(out) >= 1
        assert all(len(chunk) <= 60 for chunk in out)

    def test_split_long_text(self) -> None:
        c = RecursiveChunker(chunk_size=40, chunk_overlap=8)
        text = "слово " * 100
        out = c.split(text)
        assert len(out) >= 2
        for chunk in out:
            assert len(chunk) <= 60

    def test_overlap_preserves_continuity(self) -> None:
        c = RecursiveChunker(chunk_size=50, chunk_overlap=10)
        text = (
            "Параграф первый — содержит несколько предложений. "
            "Параграф второй — тоже содержит много слов. "
            "Параграф третий завершает текст."
        )
        out = c.split(text)
        assert len(out) >= 2

    def test_short_text_single_chunk(self) -> None:
        c = RecursiveChunker(chunk_size=200, chunk_overlap=20)
        text = "Короткий"
        out = c.split(text)
        assert out == [text]
