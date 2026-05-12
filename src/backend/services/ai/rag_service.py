"""RAG Service — Retrieval-Augmented Generation."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any

from src.backend.core.di import app_state_singleton
from src.backend.core.interfaces.vector_store import BaseVectorStore
from src.backend.services.ai.embedding_providers import (
    EmbeddingProvider,
    get_embedding_provider,
)

if TYPE_CHECKING:  # pragma: no cover
    from src.backend.infrastructure.cache.rag.three_tier import ThreeTierRagCache

__all__ = ("RAGService", "get_rag_service")

logger = logging.getLogger(__name__)


class RAGService:
    """Retrieval-Augmented Generation — загрузка, поиск, обогащение промптов.

    Embedding-провайдер и vector store инжектятся через DI; оба компонента
    выбираются по ``rag_settings`` (vector_backend, embedding_provider).
    Опциональный ``cache: ThreeTierRagCache`` подключается через
    `setup_ai_2026` и обслуживает L1 exact, L2 semantic и L3 retrieval-tier.
    """

    def __init__(
        self,
        store: BaseVectorStore,
        embedder: EmbeddingProvider | None = None,
        cache: ThreeTierRagCache | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder or get_embedding_provider()
        self._cache = cache

    @staticmethod
    def _cache_key(
        *,
        system_prompt: str,
        query: str,
        top_k: int,
        namespace: str | None,
    ) -> str:
        """Стабильный SHA-256 ключ для L1/L2 lookup на уровне augment."""
        material = f"{system_prompt}\0{query}\0{int(top_k)}\0{namespace or ''}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

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
        await self._invalidate_namespace(namespace)
        return doc_id

    async def _invalidate_namespace(self, namespace: str | None) -> None:
        """Сбрасывает закэшированные ответы по namespace-tag."""
        if self._cache is None or not namespace:
            return
        try:
            await self._cache.invalidate_by_tag(f"namespace:{namespace}")
        except Exception as exc:  # noqa: BLE001
            logger.debug("RAG cache invalidate skipped: %s", exc)

    async def search(
        self, query: str, top_k: int = 5, namespace: str | None = None
    ) -> list[dict[str, Any]]:
        """Семантический поиск с использованием L3 retrieval-tier."""
        if self._cache is not None:
            chunks, tier = await self._cache.lookup_chunks(query, namespace=namespace)
            if chunks is not None:
                logger.debug("RAG retrieval hit on tier %s (namespace=%s)", tier, namespace)
                return chunks

        embedding = (await self._embed([query]))[0]

        where = None
        if namespace:
            where = {"namespace": namespace}

        results = await self._store.query(
            embedding=embedding, top_k=top_k, where=where
        )

        if self._cache is not None and results:
            try:
                await self._cache.store_chunks(query, results, namespace=namespace)
            except Exception as exc:  # noqa: BLE001
                logger.debug("RAG L3 store skipped: %s", exc)
        return results

    async def augment_prompt(
        self,
        query: str,
        system_prompt: str = "",
        top_k: int = 5,
        namespace: str | None = None,
    ) -> str:
        """Inject RAG-контекста в промпт с поддержкой L1/L2 cache."""
        tenant_key = self._cache_key(
            system_prompt=system_prompt,
            query=query,
            top_k=top_k,
            namespace=namespace,
        )
        if self._cache is not None:
            cached, tier = await self._cache.lookup_answer(tenant_key, tenant=namespace)
            if isinstance(cached, str):
                logger.debug(
                    "RAG augment hit on tier %s (namespace=%s)", tier, namespace
                )
                return cached

        results = await self.search(query, top_k=top_k, namespace=namespace)

        if not results:
            answer = (
                f"{system_prompt}\n\nВопрос: {query}" if system_prompt else query
            )
        else:
            context_parts = [r["document"] for r in results if r.get("document")]
            context = "\n---\n".join(context_parts)
            answer = (
                f"{system_prompt}\n\n"
                f"Контекст из базы знаний:\n{context}\n\nВопрос: {query}"
            )

        if self._cache is not None:
            try:
                await self._cache.store_answer(tenant_key, answer, tenant=namespace)
            except Exception as exc:  # noqa: BLE001
                logger.debug("RAG augment store skipped: %s", exc)
        return answer

    async def augment_prompt_with_citations(
        self,
        query: str,
        system_prompt: str = "",
        top_k: int = 5,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """Возвращает обогащённый prompt + citations (doc_id, chunk_idx)."""
        results = await self.search(query, top_k=top_k, namespace=namespace)
        prompt = await self.augment_prompt(
            query, system_prompt=system_prompt, top_k=top_k, namespace=namespace
        )
        citations: list[dict[str, Any]] = []
        for r in results:
            meta = r.get("metadata") or {}
            citations.append(
                {
                    "doc_id": meta.get("doc_id"),
                    "chunk_idx": meta.get("chunk_idx"),
                    "namespace": meta.get("namespace") or namespace,
                    "score": r.get("score"),
                }
            )
        return {"prompt": prompt, "citations": citations}

    async def delete(self, document_id: str) -> bool:
        """Удаляет документ из индекса (по chunk-id'ам или doc_id)."""
        try:
            await self._store.delete([document_id])
            await self._invalidate_namespace(None)
            return True
        except Exception:
            return False

    async def delete_collection(self, namespace: str) -> int:
        """Удаляет все документы из логической партиции (namespace).

        Использует ``BaseVectorStore.delete_where({"namespace": namespace})``.
        Возвращает количество удалённых chunks. При ошибке — 0.
        """
        try:
            removed = int(await self._store.delete_where({"namespace": namespace}))
            await self._invalidate_namespace(namespace)
            return removed
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
