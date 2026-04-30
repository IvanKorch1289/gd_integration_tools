"""Vector store backends — Qdrant, Chroma, FAISS реализации.

ABC ``BaseVectorStore`` вынесен в ``core/interfaces/vector_store.py``
(Wave 6) — здесь лежат конкретные реализации.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces.vector_store import BaseVectorStore

__all__ = (
    "BaseVectorStore",
    "ChromaVectorStore",
    "FAISSVectorStore",
    "QdrantVectorStore",
    "get_vector_store",
)

logger = logging.getLogger(__name__)


class QdrantVectorStore(BaseVectorStore):
    """Vector store через Qdrant (default backend)."""

    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection_name: str = "gd_rag",
        api_key: str | None = None,
        vector_size: int = 384,
    ) -> None:
        self._url = url
        self._collection_name = collection_name
        self._api_key = api_key
        self._vector_size = vector_size
        self._client: Any = None
        self._collection_ready = False

    async def _client_instance(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from qdrant_client import AsyncQdrantClient
        except ImportError as exc:
            raise RuntimeError(
                "qdrant-client не установлен — добавьте в зависимости проекта"
            ) from exc
        self._client = AsyncQdrantClient(url=self._url, api_key=self._api_key)
        return self._client

    async def _ensure_collection(self) -> Any:
        client = await self._client_instance()
        if self._collection_ready:
            return client
        from qdrant_client.http.exceptions import UnexpectedResponse
        from qdrant_client.models import Distance, VectorParams

        try:
            await client.get_collection(self._collection_name)
        except UnexpectedResponse, ValueError:
            await client.create_collection(
                collection_name=self._collection_name,
                vectors_config=VectorParams(
                    size=self._vector_size, distance=Distance.COSINE
                ),
            )
            logger.info("Qdrant collection '%s' created", self._collection_name)
        self._collection_ready = True
        return client

    async def upsert(
        self,
        embeddings: list[list[float]],
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        from qdrant_client.models import PointStruct

        client = await self._ensure_collection()
        points = [
            PointStruct(
                id=ids[i],
                vector=embeddings[i],
                payload={
                    "document": documents[i],
                    **(metadatas[i] if metadatas and i < len(metadatas) else {}),
                },
            )
            for i in range(len(ids))
        ]
        await client.upsert(collection_name=self._collection_name, points=points)

    async def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = await self._ensure_collection()
        query_filter: Filter | None = None
        if where:
            query_filter = Filter(
                must=[
                    FieldCondition(key=key, match=MatchValue(value=value))
                    for key, value in where.items()
                ]
            )
        results = await client.search(
            collection_name=self._collection_name,
            query_vector=embedding,
            limit=top_k,
            query_filter=query_filter,
        )
        return [
            {
                "id": str(r.id),
                "document": (r.payload or {}).get("document", ""),
                "metadata": {
                    k: v for k, v in (r.payload or {}).items() if k != "document"
                },
                "distance": 1.0 - r.score,
            }
            for r in results
        ]

    async def delete(self, ids: list[str]) -> None:
        from qdrant_client.models import PointIdsList

        client = await self._ensure_collection()
        await client.delete(
            collection_name=self._collection_name,
            points_selector=PointIdsList(points=list(ids)),
        )

    async def count(self) -> int:
        client = await self._ensure_collection()
        result = await client.count(collection_name=self._collection_name, exact=True)
        return int(result.count)


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


def get_vector_store(backend: str | None = None, **kwargs: Any) -> BaseVectorStore:
    """Фабрика vector store. Если ``backend`` не указан — берёт значение
    из ``rag_settings.vector_backend`` (default ``qdrant``).
    """
    from src.core.config.rag import rag_settings

    backend_name = (backend or rag_settings.vector_backend).lower()

    match backend_name:
        case "qdrant":
            return QdrantVectorStore(
                url=kwargs.get("url", rag_settings.qdrant_url),
                collection_name=kwargs.get(
                    "collection_name", rag_settings.qdrant_collection
                ),
                api_key=kwargs.get("api_key", rag_settings.qdrant_api_key),
                vector_size=kwargs.get("vector_size", 384),
            )
        case "chroma":
            return ChromaVectorStore(
                host=kwargs.get("host", rag_settings.chroma_host),
                port=kwargs.get("port", rag_settings.chroma_port),
                collection_name=kwargs.get(
                    "collection_name", rag_settings.chroma_collection
                ),
            )
        case "faiss":
            return FAISSVectorStore(dimension=kwargs.get("dimension", 384))
        case _:
            raise ValueError(
                f"Неизвестный vector_backend: {backend_name!r}. "
                "Поддерживается: qdrant, chroma, faiss."
            )
