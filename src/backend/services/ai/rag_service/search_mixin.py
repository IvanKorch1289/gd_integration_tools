from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from src.backend.core.logging import get_logger
from src.backend.core.tenancy import current_tenant

logger = get_logger(__name__)


def _resolve_effective_tenant_id(tenant_id: str | None) -> str | None:
    """Резолвит эффективный ``tenant_id`` для retrieval-фильтра (Sprint 2.6).

    Контракт:
        * Non-empty explicit (``"bank_x"``) → возвращается as-is,
          override'ит ``TenantContext``.
        * Empty explicit (``""``) → ``None`` (явный opt-out фильтра,
          legacy passthrough даже при active ``tenant_scope``).
        * ``None`` без ``tenant_scope`` → ``None`` (legacy).
        * ``None`` внутри ``tenant_scope`` → ``ctx.tenant_id``.

    Args:
        tenant_id: Явный kwarg из ``SearchMixin.search`` (default ``None``).

    Returns:
        Эффективный tenant_id для фильтра или ``None``, если фильтр
        применять не нужно.
    """
    if tenant_id is not None:
        return tenant_id or None
    ctx = current_tenant()
    return ctx.tenant_id if ctx is not None else None


def _build_where(namespace: str | None, tenant_id: str | None) -> dict[str, Any] | None:
    """Строит compound where-фильтр для ``vector_store.query`` (Sprint 2.6).

    Комбинирует ``namespace`` и ``tenant_id`` в один dict, чтобы backend
    мог применить оба ограничения за один проход. Возвращает ``None``,
    если оба ограничения отсутствуют — backward-compat с pre-Sprint 2.6
    поведением (``where=None`` passthrough).

    Args:
        namespace: Namespace-фильтр (``None`` → пропускается).
        tenant_id: Tenant-фильтр (``None`` → пропускается).

    Returns:
        ``dict`` с непустыми полями или ``None``.
    """
    where: dict[str, Any] = {}
    if namespace:
        where["namespace"] = namespace
    if tenant_id:
        where["tenant_id"] = tenant_id
    return where or None


def _filter_chunks_by_tenant(
    chunks: list[dict[str, Any]], tenant_id: str | None
) -> list[dict[str, Any]]:
    """Post-filter retrieval chunks по ``metadata.tenant_id`` (Sprint 2.6).

    Defence-in-depth для vector-store backend'ов (FAISS, in-memory),
    которые игнорируют ``where``-фильтр: даже если store вернул чужие
    chunks, ``_filter_chunks_by_tenant`` отрежет их на стороне Python.

    Контракт:
        * ``tenant_id=None`` → passthrough (legacy / opt-out).
        * Chunks без ``metadata`` или без ``metadata.tenant_id`` →
          отбрасываются (legacy-ingest без tenant-tag — не должно
          попадать к tenant-scoped потребителю).

    Args:
        chunks: Список retrieval-чанков из vector store / cache.
        tenant_id: Эффективный tenant_id (None → passthrough).

    Returns:
        Отфильтрованный список chunks (исходный объект не мутируется).
    """
    if tenant_id is None:
        return chunks
    return [
        chunk
        for chunk in chunks
        if (chunk.get("metadata") or {}).get("tenant_id") == tenant_id
    ]


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
        self,
        query: str,
        top_k: int = 5,
        namespace: str | None = None,
        *,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Семантический поиск с использованием L3 retrieval-tier.

        Sprint 2.6: добавлен ``tenant_id`` kwarg для cross-tenant изоляции.
        При active ``tenant_scope`` (или explicit ``tenant_id``) фильтр
        применяется в трёх местах: (1) ``where`` для vector store, (2)
        ``tenant`` для L3 cache keys, (3) post-filter для defence-in-depth
        против backend'ов, игнорирующих ``where`` (FAISS/in-memory).

        ``tenant_id=""`` — явный opt-out (legacy passthrough даже при
        active scope); ``tenant_id=None`` — fallback на ``TenantContext``
        ContextVar (default multi-tenant behavior).
        """
        effective_tenant = _resolve_effective_tenant_id(tenant_id)

        if self._cache is not None:
            chunks, tier = await self._cache.lookup_chunks(
                query, tenant=effective_tenant, namespace=namespace
            )
            if chunks is not None:
                filtered = _filter_chunks_by_tenant(chunks, effective_tenant)
                if filtered:
                    logger.debug(
                        "RAG retrieval hit on tier %s (tenant=%s, namespace=%s)",
                        tier,
                        effective_tenant,
                        namespace,
                    )
                    return filtered
                # Cache вернул только чужие chunks (cross-tenant pollution) —
                # fall through в vector store, не возвращаем пустой результат
                # как 200 (silent-leak risk).

        embedding = (await self._embed([query]))[0]

        where = _build_where(namespace, effective_tenant)

        results = await self._store.query(embedding=embedding, top_k=top_k, where=where)
        results = _filter_by_embedding_version(results)
        results = _filter_chunks_by_tenant(results, effective_tenant)

        if self._cache is not None and results:
            try:
                await self._cache.store_chunks(
                    query, results, tenant=effective_tenant, namespace=namespace
                )
            except Exception as exc:
                logger.debug("RAG L3 store skipped: %s", exc)
        return results
