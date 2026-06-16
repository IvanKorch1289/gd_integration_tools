from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from src.backend.infrastructure.logging.factory import get_logger

logger = get_logger(__name__)


def _filter_by_embedding_version(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter retrieval results by embedding-model match.

    Block 3.5 (gap-ai-3.5, ADR-0074): если ``rag_settings.embedding_strict_mode``,
    отбрасывает chunks, у которых ``metadata.embedding_model`` задан и не
    совпадает с ``rag_settings.embedding_model``. Legacy-chunks без поля
    ``embedding_model`` пропускаются. В non-strict режиме pass-through с
    warn-only (counter инкрементируется вызывающей стороной).
    """
    from src.backend.core.config.rag import rag_settings

    if not rag_settings.embedding_strict_mode:
        return results

    current_model = rag_settings.embedding_model
    filtered: list[dict[str, Any]] = []
    for hit in results:
        meta = hit.get("metadata") or {}
        chunk_model = meta.get("embedding_model")
        if chunk_model is not None and chunk_model != current_model:
            logger.debug(
                "RAG embedding mismatch dropped in strict mode: "
                "chunk_model=%s current_model=%s",
                chunk_model,
                current_model,
            )
            continue
        filtered.append(hit)
    return filtered


def _format_context_with_sources(results: list[dict[str, Any]]) -> str:
    """Format retrieved chunks into a context string with [doc_id:chunk_idx] markers.

    Если ``rag_settings.source_attribution_enabled`` (default True), каждый chunk
    дополняется маркером ``[источник: <source_id>]`` с приоритетом
    metadata.source > filename > doc_id > id. Chunks без document пропускаются.
    """
    from src.backend.core.config.rag import rag_settings

    parts: list[str] = []
    for hit in results:
        document = hit.get("document", "")
        if not document:
            continue
        meta = hit.get("metadata") or {}
        doc_id = meta.get("doc_id", "?")
        chunk_idx = meta.get("chunk_idx", 0)
        if rag_settings.source_attribution_enabled:
            source_id = _extract_source_id(hit)
            parts.append(f"[{doc_id}:{chunk_idx}] [источник: {source_id}] {document}")
        else:
            parts.append(f"[{doc_id}:{chunk_idx}] {document}")
    return "\n\n".join(parts)


def _extract_source_id(chunk: dict[str, Any]) -> str:
    """Extract the source identifier from a retrieved chunk.

    Priority: metadata.source > metadata.filename > metadata.doc_id > chunk.id.

    S154 W1 stub (post factcheck): minimal implementation. Used by
    source-attribution logic and exposed via the RAG service for tests.
    Per-test contract (test_rag_source_attribution.py):
    1. ``metadata.source`` if explicitly set.
    2. ``metadata.filename`` if no source.
    3. ``metadata.doc_id`` if no source/filename.
    4. ``chunk.id`` as last resort.
    """
    metadata = chunk.get("metadata") or {}
    if metadata.get("source"):
        return metadata["source"]
    if metadata.get("filename"):
        return metadata["filename"]
    if metadata.get("doc_id"):
        return metadata["doc_id"]
    return chunk.get("id", "")


from src.backend.services.ai.rag_service._protocol import _RAGServiceProtocol


class SearchMixin(_RAGServiceProtocol):
    """search (semantic search with cache) для RAGService. S64 W4 extraction."""

    __slots__ = ()

    async def search(
        self, query: str, top_k: int = 5, namespace: str | None = None
    ) -> list[dict[str, Any]]:
        """Семантический поиск с использованием L3 retrieval-tier."""
        if self._cache is not None:
            chunks, tier = await self._cache.lookup_chunks(query, namespace=namespace)
            if chunks is not None:
                logger.debug(
                    "RAG retrieval hit on tier %s (namespace=%s)", tier, namespace
                )
                return chunks

        embedding = (await self._embed([query]))[0]

        where = None
        if namespace:
            where = {"namespace": namespace}

        results = await self._store.query(embedding=embedding, top_k=top_k, where=where)
        results = _filter_by_embedding_version(results)

        if self._cache is not None and results:
            try:
                await self._cache.store_chunks(query, results, namespace=namespace)
            except Exception as exc:
                logger.debug("RAG L3 store skipped: %s", exc)
        return results
