"""Vector store abstraction — Chroma, FAISS backends."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

__all__ = (
    "BaseVectorStore",
    "ChromaVectorStore",
    "FAISSVectorStore",
    "get_vector_store",
)

logger = logging.getLogger(__name__)


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


class ChromaVectorStore(BaseVectorStore):
    """Vector store через Chroma DB."""

    def __init__(
        self, host: str = "localhost", port: int = 8000, collection_name: str = "gd_rag"
    ) -> None:
        self._host = host
        self._port = port
        self._collection_name = collection_name
        self._client: Any = None
        self._collection: Any = None

    async def _ensure_collection(self) -> Any:
        if self._collection is not None:
            return self._collection

        import asyncio

        import chromadb

        self._client = await asyncio.to_thread(
            chromadb.HttpClient, host=self._host, port=self._port
        )
        self._collection = await asyncio.to_thread(
            self._client.get_or_create_collection, self._collection_name
        )
        logger.info("Chroma collection '%s' ready", self._collection_name)
        return self._collection

    async def upsert(
        self,
        embeddings: list[list[float]],
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        import asyncio

        collection = await self._ensure_collection()
        kwargs: dict[str, Any] = {
            "ids": ids,
            "embeddings": embeddings,
            "documents": documents,
        }
        if metadatas:
            kwargs["metadatas"] = metadatas
        await asyncio.to_thread(collection.upsert, **kwargs)

    async def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        import asyncio

        collection = await self._ensure_collection()
        kwargs: dict[str, Any] = {
            "query_embeddings": [embedding],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        results = await asyncio.to_thread(collection.query, **kwargs)

        items = []
        for i, doc_id in enumerate(results["ids"][0]):
            items.append(
                {
                    "id": doc_id,
                    "document": results["documents"][0][i]
                    if results["documents"]
                    else "",
                    "metadata": results["metadatas"][0][i]
                    if results["metadatas"]
                    else {},
                    "distance": results["distances"][0][i]
                    if results["distances"]
                    else 0.0,
                }
            )
        return items

    async def delete(self, ids: list[str]) -> None:
        import asyncio

        collection = await self._ensure_collection()
        await asyncio.to_thread(collection.delete, ids=ids)

    async def count(self) -> int:
        import asyncio

        collection = await self._ensure_collection()
        return await asyncio.to_thread(collection.count)


class FAISSVectorStore(BaseVectorStore):
    """In-memory FAISS vector store (для разработки и тестов)."""

    def __init__(self, dimension: int = 384) -> None:
        self._dimension = dimension
        self._index: Any = None
        self._id_map: dict[str, int] = {}
        self._docs: dict[str, str] = {}
        self._metas: dict[str, dict[str, Any]] = {}
        self._next_idx = 0

    def _ensure_index(self) -> Any:
        if self._index is not None:
            return self._index
        import faiss

        self._index = faiss.IndexFlatL2(self._dimension)
        return self._index

    async def upsert(
        self,
        embeddings: list[list[float]],
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        import numpy as np

        index = self._ensure_index()
        vectors = np.array(embeddings, dtype="float32")
        index.add(vectors)

        for i, doc_id in enumerate(ids):
            self._id_map[doc_id] = self._next_idx + i
            self._docs[doc_id] = documents[i]
            if metadatas:
                self._metas[doc_id] = metadatas[i]
        self._next_idx += len(ids)

    async def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        import numpy as np

        index = self._ensure_index()
        if index.ntotal == 0:
            return []

        query_vec = np.array([embedding], dtype="float32")
        distances, indices = index.search(query_vec, min(top_k, index.ntotal))

        idx_to_id = {v: k for k, v in self._id_map.items()}
        results = []
        for i, idx in enumerate(indices[0]):
            if idx < 0:
                continue
            doc_id = idx_to_id.get(int(idx), "")
            results.append(
                {
                    "id": doc_id,
                    "document": self._docs.get(doc_id, ""),
                    "metadata": self._metas.get(doc_id, {}),
                    "distance": float(distances[0][i]),
                }
            )
        return results

    async def delete(self, ids: list[str]) -> None:
        for doc_id in ids:
            self._id_map.pop(doc_id, None)
            self._docs.pop(doc_id, None)
            self._metas.pop(doc_id, None)

    async def count(self) -> int:
        return len(self._docs)


def get_vector_store(backend: str = "chroma", **kwargs: Any) -> BaseVectorStore:
    """Фабрика для vector store."""
    if backend == "faiss":
        return FAISSVectorStore(**kwargs)
    from src.core.config.rag import rag_settings

    return ChromaVectorStore(
        host=kwargs.get("host", rag_settings.chroma_host),
        port=kwargs.get("port", rag_settings.chroma_port),
        collection_name=kwargs.get("collection_name", rag_settings.chroma_collection),
    )
