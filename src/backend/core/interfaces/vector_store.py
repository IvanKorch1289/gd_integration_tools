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

    async def delete_where(self, where: dict[str, Any]) -> int:
        """Удаляет документы по metadata-фильтру, возвращает кол-во удалённых.

        Default-реализация: ``query`` (limit ~10000) → собрать ``id``'ы → ``delete``.
        Бэкенды с native filter-delete (Qdrant, Chroma) переопределяют для
        эффективности; FAISS использует in-memory сканирование.
        """
        raise NotImplementedError(
            "delete_where не поддерживается этим backend'ом — переопределите в подклассе."
        )

    async def count_where(self, where: dict[str, Any]) -> int:
        """Количество документов, проходящих metadata-фильтр.

        Default — поднять NotImplementedError; backend'ы с native count-by-filter
        переопределяют. Используется для ``RAGService.count(collection=...)``.
        """
        raise NotImplementedError(
            "count_where не поддерживается этим backend'ом — переопределите в подклассе."
        )
