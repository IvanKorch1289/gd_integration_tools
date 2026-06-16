"""Structural protocol for RAGService mixins.

Sprint 36 (tech-debt): объявляет cross-mixin атрибуты и методы,
чтобы mypy видел ``self._cache`` / ``self.search`` и т.д. внутри миксинов.
"""

from __future__ import annotations

from typing import Any, Protocol

from src.backend.core.interfaces.vector_store import BaseVectorStore
from src.backend.services.ai.embedding_providers import EmbeddingProvider


class _RAGServiceProtocol(Protocol):
    """Общий контракт для IngestMixin / SearchMixin / AugmentMixin / CollectionMixin."""

    _store: BaseVectorStore
    _embedder: EmbeddingProvider
    _cache: Any | None

    def _cache_key(
        self, *, system_prompt: str, query: str, top_k: int, namespace: str | None
    ) -> str: ...

    async def _embed(self, texts: list[str]) -> list[list[float]]: ...

    async def _invalidate_namespace(self, namespace: str | None) -> None: ...

    async def search(
        self, query: str, top_k: int = 5, namespace: str | None = None
    ) -> list[dict[str, Any]]: ...
