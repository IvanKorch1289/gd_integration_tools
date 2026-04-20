"""RAG Service — Retrieval-Augmented Generation."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.core.decorators.singleton import singleton
from app.infrastructure.clients.storage.s3_pool.vector_store import BaseVectorStore, get_vector_store

__all__ = ("RAGService", "get_rag_service")

logger = logging.getLogger(__name__)


@singleton
class RAGService:
    """Retrieval-Augmented Generation — загрузка, поиск, обогащение промптов."""

    def __init__(self, store: BaseVectorStore) -> None:
        self._store = store
        self._embedder: Any = None

    def _get_embedder(self) -> Any:
        if self._embedder is not None:
            return self._embedder

        from sentence_transformers import SentenceTransformer

        from app.core.config.rag_settings import rag_settings

        self._embedder = SentenceTransformer(rag_settings.embedding_model)
        return self._embedder

    def _chunk_text(self, text: str) -> list[str]:
        from app.core.config.rag_settings import rag_settings

        size = rag_settings.chunk_size
        overlap = rag_settings.chunk_overlap

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + size
            chunks.append(text[start:end])
            start = end - overlap
        return chunks

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        import asyncio

        model = self._get_embedder()
        embeddings = await asyncio.to_thread(
            model.encode, texts, convert_to_numpy=True
        )
        return embeddings.tolist()

    async def ingest(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        namespace: str = "default",
    ) -> str:
        """Загружает документ → chunking → embedding → vector store."""
        doc_id = hashlib.sha256(content.encode()).hexdigest()[:16]
        chunks = self._chunk_text(content)
        embeddings = await self._embed(chunks)

        ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {**(metadata or {}), "namespace": namespace, "doc_id": doc_id, "chunk_idx": i}
            for i in range(len(chunks))
        ]

        await self._store.upsert(
            embeddings=embeddings,
            documents=chunks,
            ids=ids,
            metadatas=metadatas,
        )

        logger.info("Ingested document %s: %d chunks", doc_id, len(chunks))
        return doc_id

    async def search(
        self,
        query: str,
        top_k: int = 5,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """Семантический поиск."""
        embedding = (await self._embed([query]))[0]

        where = None
        if namespace:
            where = {"namespace": namespace}

        return await self._store.query(
            embedding=embedding, top_k=top_k, where=where
        )

    async def augment_prompt(
        self,
        query: str,
        system_prompt: str = "",
        top_k: int = 5,
        namespace: str | None = None,
    ) -> str:
        """Inject RAG-контекста в промпт."""
        results = await self.search(query, top_k=top_k, namespace=namespace)

        if not results:
            return f"{system_prompt}\n\nВопрос: {query}" if system_prompt else query

        context_parts = [r["document"] for r in results if r.get("document")]
        context = "\n---\n".join(context_parts)

        return (
            f"{system_prompt}\n\nКонтекст из базы знаний:\n{context}"
            f"\n\nВопрос: {query}"
        )

    async def delete(self, document_id: str) -> bool:
        """Удаляет документ из индекса."""
        try:
            await self._store.delete([document_id])
            return True
        except Exception:
            return False

    async def count(self) -> int:
        """Количество документов в store."""
        return await self._store.count()


def get_rag_service() -> RAGService:
    return RAGService(store=get_vector_store())
