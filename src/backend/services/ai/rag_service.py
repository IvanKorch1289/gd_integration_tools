"""RAG Service — Retrieval-Augmented Generation."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from src.backend.core.di import app_state_singleton
from src.backend.core.interfaces.vector_store import BaseVectorStore
from src.backend.services.ai.embedding_providers import (
    EmbeddingProvider,
    get_embedding_provider,
)

__all__ = ("RAGService", "get_rag_service")

logger = logging.getLogger(__name__)


class RAGService:
    """Retrieval-Augmented Generation — загрузка, поиск, обогащение промптов.

    Embedding-провайдер и vector store инжектятся через DI; оба компонента
    выбираются по ``rag_settings`` (vector_backend, embedding_provider).
    """

    def __init__(
        self, store: BaseVectorStore, embedder: EmbeddingProvider | None = None
    ) -> None:
        self._store = store
        self._embedder = embedder or get_embedding_provider()

    def chunk_text(self, text: str) -> list[str]:
        """Разбивает текст на overlap-чанки согласно ``rag_settings``."""
        from src.backend.core.config.rag import rag_settings

        size = rag_settings.chunk_size
        overlap = rag_settings.chunk_overlap

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + size
            chunks.append(text[start:end])
            start = end - overlap
        return chunks

    # Backward-compat alias — публичный путь предпочтителен.
    _chunk_text = chunk_text

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        return await self._embedder.embed(texts)

    async def ingest(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        namespace: str = "default",
    ) -> str:
        """Загружает документ → chunking → embedding → vector store."""
        doc_id = hashlib.sha256(content.encode()).hexdigest()[:16]
        chunks = self.chunk_text(content)
        embeddings = await self._embed(chunks)

        ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                **(metadata or {}),
                "namespace": namespace,
                "doc_id": doc_id,
                "chunk_idx": i,
            }
            for i in range(len(chunks))
        ]

        await self._store.upsert(
            embeddings=embeddings, documents=chunks, ids=ids, metadatas=metadatas
        )

        logger.info("Ingested document %s: %d chunks", doc_id, len(chunks))
        return doc_id

    async def search(
        self, query: str, top_k: int = 5, namespace: str | None = None
    ) -> list[dict[str, Any]]:
        """Семантический поиск."""
        embedding = (await self._embed([query]))[0]

        where = None
        if namespace:
            where = {"namespace": namespace}

        return await self._store.query(embedding=embedding, top_k=top_k, where=where)

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
            f"{system_prompt}\n\nКонтекст из базы знаний:\n{context}\n\nВопрос: {query}"
        )

    async def delete(self, document_id: str) -> bool:
        """Удаляет документ из индекса (по chunk-id'ам или doc_id)."""
        try:
            await self._store.delete([document_id])
            return True
        except Exception:
            return False

    async def delete_collection(self, namespace: str) -> int:
        """Удаляет все документы из логической партиции (namespace).

        Использует ``BaseVectorStore.delete_where({"namespace": namespace})``.
        Возвращает количество удалённых chunks. При ошибке — 0.
        """
        try:
            return int(await self._store.delete_where({"namespace": namespace}))
        except NotImplementedError:
            logger.warning(
                "delete_where не поддерживается backend'ом — namespace %s не очищен",
                namespace,
            )
            return 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("delete_collection(%s) failed: %s", namespace, exc)
            return 0

    async def get_collection_stats(self, namespace: str) -> dict[str, Any]:
        """Статистика по namespace: количество chunks + базовые метаданные.

        Возвращает: ``{"namespace": str, "count": int, "exists": bool}``.
        Backend'ы без ``count_where`` отдают ``count=0``.
        """
        try:
            cnt = int(await self._store.count_where({"namespace": namespace}))
        except NotImplementedError:
            cnt = 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_collection_stats(%s) failed: %s", namespace, exc)
            cnt = 0
        return {"namespace": namespace, "count": cnt, "exists": cnt > 0}

    async def count(self, collection: str | None = None) -> int:
        """Количество документов: всего или в конкретной namespace.

        ``collection`` — если задан, фильтрует по metadata ``namespace``.
        Возвращает 0 при недоступности backend.
        """
        try:
            if collection is None:
                return int(await self._store.count())
            return int(await self._store.count_where({"namespace": collection}))
        except NotImplementedError:
            return 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("count(%s) failed: %s", collection, exc)
            return 0


@app_state_singleton("rag_service")
def get_rag_service() -> RAGService:
    """Возвращает singleton ``RAGService`` из ``app.state.rag_service``.

    Регистрация выполняется в ``infrastructure/application/service_setup.py``
    при старте приложения; здесь — только accessor.
    """
    raise RuntimeError(
        "rag_service не зарегистрирован — убедитесь, что register_app_state() "
        "и infrastructure.application.service_setup были вызваны при старте."
    )
