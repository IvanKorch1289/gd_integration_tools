from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    pass


class IngestMixin:
    """ingest ops (_cache_key + chunk_text + _embed + ingest + _invalidate_namespace) для RAGService. S64 W4 extraction."""

    __slots__ = ()

    @staticmethod
    def _cache_key(
        *, system_prompt: str, query: str, top_k: int, namespace: str | None
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
        except Exception as exc:
            logger.debug("RAG cache invalidate skipped: %s", exc)
