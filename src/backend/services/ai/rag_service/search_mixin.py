from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from src.backend.infrastructure.logging.factory import get_logger

logger = get_logger(__name__)


def _filter_by_embedding_version(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter retrieval results by embedding-version match.

    .. note::
        S140 W4 stub (post factcheck): embedding-version tracking not
        yet implemented. Currently a no-op pass-through. To upgrade:
        compare each result's metadata.embedding_version against
        self._embedder.version and drop mismatches. Stored metadata
        field is reserved (see ``ingest_mixin.upsert``).
    """
    return results


def _format_context_with_sources(results: list[dict[str, Any]]) -> str:
    """Format retrieved chunks into a context string with [doc_id:chunk_idx] markers.

    .. note::
        S140 W4 stub: minimal format — concatenates documents with
        index markers. Full version would include source paths, scores,
        freshness labels (see FreshnessLabel in rag_augment.py).
    """
    parts: list[str] = []
    for hit in results:
        meta = hit.get("metadata") or {}
        doc_id = meta.get("doc_id", "?")
        chunk_idx = meta.get("chunk_idx", 0)
        document = hit.get("document", "")
        parts.append(f"[{doc_id}:{chunk_idx}] {document}")
    return "\n\n".join(parts)


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
