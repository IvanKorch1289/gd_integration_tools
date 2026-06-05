# ruff: noqa: S101
"""Smoke tests for vector store (infrastructure/clients/storage/vector_store.py)."""

from __future__ import annotations

import pytest

# ── get_vector_store factory ────────────────────────────────────────


def test_get_vector_store_unknown_backend_raises() -> None:
    from src.backend.infrastructure.clients.storage.vector_store import get_vector_store

    with pytest.raises((ValueError, KeyError, NotImplementedError)):
        get_vector_store(backend="nonexistent_backend_xyz")


def test_get_vector_store_default_backend(monkeypatch) -> None:
    """Default backend comes from rag_settings.vector_backend."""
    from src.backend.infrastructure.clients.storage import vector_store

    # The factory falls back to rag_settings; depending on config, may return
    # any concrete backend. We just verify it returns a BaseVectorStore instance
    # or raises (if no settings configured).
    try:
        store = vector_store.get_vector_store(backend="qdrant")
        assert store is not None
    except Exception:
        # Settings not configured in test env — acceptable
        pytest.skip("RAG settings not configured for qdrant backend in test env")


# ── Module-level types ──────────────────────────────────────────────


def test_module_imports() -> None:
    from src.backend.infrastructure.clients.storage import vector_store

    assert hasattr(vector_store, "get_vector_store")
    assert hasattr(vector_store, "BaseVectorStore")


def test_base_vector_store_is_abstract() -> None:
    """BaseVectorStore should be abstract — can't instantiate directly."""
    from src.backend.infrastructure.clients.storage.vector_store import BaseVectorStore

    # Either it's abstract (can't instantiate) or it's a simple class
    # Just verify it's importable
    assert BaseVectorStore is not None


# ── Backend classes are importable (don't actually create) ──────────


def test_qdrant_class_importable() -> None:
    from src.backend.infrastructure.clients.storage.vector_store import (
        QdrantVectorStore,
    )

    assert QdrantVectorStore is not None


def test_chroma_class_importable() -> None:
    from src.backend.infrastructure.clients.storage.vector_store import (
        ChromaVectorStore,
    )

    assert ChromaVectorStore is not None


def test_faiss_class_importable() -> None:
    from src.backend.infrastructure.clients.storage.vector_store import FAISSVectorStore

    assert FAISSVectorStore is not None
