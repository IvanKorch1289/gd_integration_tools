"""Tests for infrastructure.ai.vector_store compatibility alias."""

from __future__ import annotations

import importlib

import pytest

import src.backend.infrastructure.ai.vector_store as vector_store_module
from src.backend.infrastructure.clients.storage.vector_store import (
    QdrantVectorStore as CanonicalQdrantVectorStore,
)


@pytest.mark.unit
class TestVectorStoreAlias:
    def test_qdrant_vector_store_re_export(self) -> None:
        mod = importlib.reload(vector_store_module)
        assert mod.QdrantVectorStore is CanonicalQdrantVectorStore

    def test_all_exports(self) -> None:
        mod = importlib.reload(vector_store_module)
        assert mod.__all__ == ("QdrantVectorStore",)
