"""ABC ``BaseVectorStore`` — контракт vector-store бэкендов RAG.

Wave 6: вынесено из ``infrastructure/clients/storage/vector_store.py``,
чтобы services могли импортировать только контракт без зависимости
от конкретных реализаций (Qdrant/Chroma/FAISS).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

__all__ = ("BaseVectorStore",)


class BaseVectorStore(ABC):
    """Абстрактный vector store для RAG."""

    @abstractmethod
    async def upsert(
        self,
        embeddings: list[list[float]],
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None: ...

    @abstractmethod
    async def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def delete(self, ids: list[str]) -> None: ...

    @abstractmethod
    async def count(self) -> int: ...
