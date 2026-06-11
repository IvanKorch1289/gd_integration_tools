from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    pass


class SearchMixin:
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
