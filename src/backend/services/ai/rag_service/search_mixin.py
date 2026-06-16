from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _filter_by_embedding_version(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter retrieval results by embedding-version match.

    S152 W1: имплементирован (S140 W4 был no-op stub). Сравнивает
    ``chunk.metadata.embedding_model`` с текущим ``rag_settings.embedding_model``.
    Legacy chunks (без ``embedding_model``) пропускаются всегда.

    Strict mode (``rag_settings.embedding_strict_mode=True``): mismatch → drop.
    Warn mode: mismatch → pass + log warning (counter increment через logger).
    """
    from src.backend.core.config import rag

    current_model = getattr(rag.rag_settings, "embedding_model", None)
    if not current_model:
        return results

    strict = bool(getattr(rag.rag_settings, "embedding_strict_mode", False))
    filtered: list[dict[str, Any]] = []
    for hit in results:
        chunk_model = (hit.get("metadata") or {}).get("embedding_model")
        if chunk_model is None or chunk_model == current_model:
            # legacy (no provenance) OR match → pass
            filtered.append(hit)
            continue
        # mismatch
        if strict:
            logger.debug(
                "RAG filter: drop chunk id=%s (model=%s != current=%s)",
                hit.get("id"),
                chunk_model,
                current_model,
            )
            continue
        logger.warning(
            "RAG filter warn: chunk id=%s model=%s != current=%s (passing в warn mode)",
            hit.get("id"),
            chunk_model,
            current_model,
        )
        filtered.append(hit)
    return filtered


def _extract_source_id(chunk: dict[str, Any]) -> str:
    """Extract source-id from chunk по priority: source > filename > doc_id > id.

    S152 W2: имплементирован (раньше отсутствовал, S140 W4 не дописал).
    Priority из ADR-0074 block 3.3.
    """
    meta = chunk.get("metadata") or {}
    for key in ("source", "filename", "doc_id"):
        val = meta.get(key)
        if val:
            return str(val)
    chunk_id = chunk.get("id")
    return str(chunk_id) if chunk_id else ""


def _format_context_with_sources(
    results: list[dict[str, Any]],
) -> str:
    """Format retrieved chunks into a context string.

    S152 W2: имплементирован source attribution (S140 W4 был stub без
    source markers). Формат:

    * ``source_attribution_enabled=True`` (default): ``[источник: <src>]\n\n
      [<doc_id>:<chunk_idx>] <document>`` per chunk (joined by blank line).
    * ``source_attribution_enabled=False``: passthrough
      ``[<doc_id>:<chunk_idx>] <document>``.
    * Chunks без ``document`` field пропускаются.
    """
    from src.backend.core.config import rag

    attribution = bool(
        getattr(rag.rag_settings, "source_attribution_enabled", True)
    )
    parts: list[str] = []
    for hit in results:
        document = hit.get("document")
        if not document:
            continue
        meta = hit.get("metadata") or {}
        doc_id = meta.get("doc_id", "?")
        chunk_idx = meta.get("chunk_idx", 0)
        if attribution:
            source_id = _extract_source_id(hit)
            parts.append(
                f"[источник: {source_id}]\n\n[{doc_id}:{chunk_idx}] {document}"
            )
        else:
            parts.append(f"[{doc_id}:{chunk_idx}] {document}")
    return "\n\n".join(parts)


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
