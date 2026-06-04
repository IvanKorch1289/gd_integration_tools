"""Tests for src.backend.core.config.rag."""

from __future__ import annotations

import pytest

from src.backend.core.config.rag import RAGSettings


class TestRAGSettings:
    def test_defaults(self) -> None:
        s = RAGSettings()
        assert s.vector_backend == "qdrant"
        assert s.enabled is False
        assert s.chunk_size == 512
        assert s.top_k == 5

    def test_custom(self) -> None:
        s = RAGSettings(
            vector_backend="chroma", enabled=True, chunk_size=1024, top_k=10
        )
        assert s.vector_backend == "chroma"
        assert s.enabled is True
        assert s.chunk_size == 1024
        assert s.top_k == 10

    def test_bounds(self) -> None:
        with pytest.raises(Exception):
            RAGSettings(chunk_size=32)
        with pytest.raises(Exception):
            RAGSettings(top_k=0)
