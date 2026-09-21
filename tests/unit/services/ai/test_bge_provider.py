"""Тесты BGE-провайдера: lazy-import + mock модели."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.backend.services.ai.embedding_providers_bge import (
    BGEM3EmbeddingProvider,
    BGERerankerV2M3,
    BGEUnavailable,
)


@pytest.mark.asyncio
async def test_bge_raises_when_flagembedding_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "FlagEmbedding", None)
    provider = BGEM3EmbeddingProvider()
    with pytest.raises(BGEUnavailable):
        await provider.embed(["hello"])


@pytest.mark.asyncio
async def test_bge_embed_uses_mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model = MagicMock()
    fake_model.encode.return_value = {"dense_vecs": [[0.1] * 1024]}
    fake_module = SimpleNamespace(
        BGEM3FlagModel=MagicMock(return_value=fake_model), FlagReranker=MagicMock()
    )
    monkeypatch.setitem(sys.modules, "FlagEmbedding", fake_module)
    provider = BGEM3EmbeddingProvider()
    vectors = await provider.embed(["hello"])
    assert len(vectors) == 1 and len(vectors[0]) == 1024


@pytest.mark.asyncio
async def test_bge_reranker_sorts_desc(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model = MagicMock()
    fake_model.compute_score.return_value = [0.2, 0.9, 0.5]
    fake_module = SimpleNamespace(
        BGEM3FlagModel=MagicMock(), FlagReranker=MagicMock(return_value=fake_model)
    )
    monkeypatch.setitem(sys.modules, "FlagEmbedding", fake_module)
    rr = BGERerankerV2M3()
    result = await rr.rerank("query", ["a", "b", "c"])
    assert [doc for doc, _ in result] == ["b", "c", "a"]


@pytest.mark.asyncio
async def test_bge_embed_empty_returns_empty() -> None:
    provider = BGEM3EmbeddingProvider()
    assert await provider.embed([]) == []
