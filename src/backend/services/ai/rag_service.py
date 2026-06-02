"""RAG Service — Retrieval-Augmented Generation."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.backend.core.di import app_state_singleton
from src.backend.core.interfaces.vector_store import BaseVectorStore
from src.backend.services.ai.embedding_providers import (
    EmbeddingProvider,
    get_embedding_provider,
)
from src.backend.services.ai.rag_augment import (
    AugmentResult,
    FreshnessLabel,
    build_augment_result,
)

if TYPE_CHECKING:  # pragma: no cover
    from src.backend.infrastructure.cache.rag.three_tier import ThreeTierRagCache

__all__ = (
    "AugmentResult",
    "FreshnessLabel",
    "RAGCitation",
    "RAGService",
    "get_rag_service",
)


@dataclass(slots=True, frozen=True)
class RAGCitation:
    """Структурированная ссылка на источник в augment_prompt_with_citations.

    Attributes:
        source_doc: Логическое имя источника (metadata.source → fallback
            на metadata.doc_id).
        chunk_id: Идентификатор чанка из vector store (поле ``id``).
        chunk_idx: Порядковый индекс чанка внутри документа.
        score: relevance score в [0.0..1.0] (``1.0 - distance`` если distance
            присутствует, иначе 0.0 — fallback для метаданных без расстояния).
        namespace: namespace источника (для multi-tenant retrieval).
    """

    source_doc: str
    chunk_id: str
    chunk_idx: int | None
    score: float
    namespace: str | None


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
        """Inject RAG-контекста в промпт с поддержкой L1/L2 cache.

        Block 3.3 (gap-ai-3.3, ADR-0074): при включённом
        ``rag_settings.source_attribution_enabled`` (default-ON) к каждому
        chunk в augmented prompt добавляется маркер ``[источник: <source>]``
        с приоритетом ``metadata.source`` → ``metadata.filename`` →
        ``metadata.doc_id`` → ``id``. LLM получает explicit attribution
        для each cited fact — критично для трассировки в банковском домене.
        """
        tenant_key = self._cache_key(
            system_prompt=system_prompt, query=query, top_k=top_k, namespace=namespace
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
            answer = f"{system_prompt}\n\nВопрос: {query}" if system_prompt else query
        else:
            context = _format_context_with_sources(results)
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
    ) -> AugmentResult:
        """Структурированный prompt + типизированные :class:`RAGCitation`.

        Возвращает :class:`AugmentResult`, в котором ``citations`` — список
        dataclass-объектов ``RAGCitation`` (а не dict). ``score`` нормируется
        к диапазону [0..1] через ``1 - distance``; при отсутствии distance —
        ``0.0``. ``source_doc`` берётся из ``metadata.source`` либо fallback
        на ``metadata.doc_id`` для обратной совместимости со старым ingester.
        """
        results = await self.search(query, top_k=top_k, namespace=namespace)
        prompt = await self.augment_prompt(
            query, system_prompt=system_prompt, top_k=top_k, namespace=namespace
        )
        citations: list[RAGCitation] = []
        for r in results:
            meta = r.get("metadata") or {}
            distance = r.get("distance")
            if distance is None:
                score = float(r.get("score") or 0.0)
            else:
                score = float(distance)
            source_doc = meta.get("source") or meta.get("doc_id") or ""
            citations.append(
                RAGCitation(
                    source_doc=str(source_doc),
                    chunk_id=str(r.get("id") or ""),
                    chunk_idx=meta.get("chunk_idx"),
                    score=score,
                    namespace=meta.get("namespace") or namespace,
                )
            )
        return AugmentResult(
            prompt=prompt,
            citations=citations,
            used_results=len(citations),
            namespace=namespace,
            top_k=top_k,
        )

    async def augment(
        self,
        query: str,
        *,
        system_prompt: str = "",
        top_k: int = 5,
        namespace: str | None = None,
        max_staleness_hours: float | None = None,
    ) -> AugmentResult:
        """Structured augment c freshness-фильтрацией (Sprint 9 K3 W4 + K4 W3).

        Возвращает :class:`AugmentResult` с распределением freshness и
        worst_freshness для UI-badge.
        """
        results = await self.search(query, top_k=top_k, namespace=namespace)
        prompt = await self.augment_prompt(
            query, system_prompt=system_prompt, top_k=top_k, namespace=namespace
        )
        return build_augment_result(
            prompt=prompt,
            raw_results=results,
            namespace=namespace,
            top_k=top_k,
            max_staleness_hours=max_staleness_hours,
        )

    async def delete(self, document_id: str) -> bool:
        """Удаляет документ из индекса (по chunk-id'ам или doc_id)."""
        try:
            await self._store.delete([document_id])
            await self._invalidate_namespace(None)
            return True
        except Exception as _:
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


def _format_context_with_sources(results: list[dict[str, Any]]) -> str:
    """Block 3.3 (gap-ai-3.3, ADR-0074): format chunks с source-маркерами.

    При ``rag_settings.source_attribution_enabled=True`` (default) — каждый
    chunk обогащается маркером ``[источник: <source_id>]``. Source-id
    извлекается с приоритетом:
        1. ``chunk.metadata.source`` (явный source);
        2. ``chunk.metadata.filename`` (filename из ingest);
        3. ``chunk.metadata.doc_id`` (legacy);
        4. ``chunk.id`` (fallback).

    При выключенном flag — passthrough (старый формат без source).

    Args:
        results: chunks от RAGService.search.

    Returns:
        Concatenated context string с source-маркерами либо без.
    """
    try:
        from src.backend.core.config.rag import rag_settings

        attribution_on = bool(getattr(rag_settings, "source_attribution_enabled", True))
    except Exception as _:  # noqa: BLE001
        attribution_on = True

    parts: list[str] = []
    for chunk in results:
        document = chunk.get("document")
        if not document:
            continue
        if not attribution_on:
            parts.append(str(document))
            continue
        source = _extract_source_id(chunk)
        parts.append(f"{document}\n[источник: {source}]" if source else str(document))
    return "\n---\n".join(parts)


def _extract_source_id(chunk: dict[str, Any]) -> str:
    """Извлекает source-id из chunk.metadata с приоритетом source→filename→doc_id→id."""
    metadata = chunk.get("metadata") or {}
    for key in ("source", "filename", "doc_id"):
        value = metadata.get(key)
        if value:
            return str(value)
    return str(chunk.get("id") or "")


def _filter_by_embedding_version(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Block 3.5 (gap-ai-3.5, ADR-0074): retrieval-side embedding version check.

    Сравнивает ``chunk.metadata.embedding_model`` с текущим
    ``rag_settings.embedding_model``. При mismatch:
        * ``RAGSettings.embedding_strict_mode=True`` — фильтрует chunk
          (исключает из retrieval);
        * False (default) — оставляет chunk + counter
          ``rag_model_mismatch_total{chunk_model, current_model}`` + log warn.

    Backward-compat: chunks без поля ``embedding_model`` в metadata
    (legacy ingest до Block 3.5) — пропускаются без проверки (counter
    `rag_model_unknown_total` инкрементируется, но не фильтрует).

    Args:
        results: List of retrieval results from vector store.

    Returns:
        Отфильтрованный список (или исходный в non-strict mode).
    """
    if not results:
        return results
    try:
        from src.backend.core.config.rag import rag_settings
    except Exception as _:  # noqa: BLE001
        return results

    current_model = getattr(rag_settings, "embedding_model", None)
    if not current_model:
        return results
    strict_mode = bool(getattr(rag_settings, "embedding_strict_mode", False))

    filtered: list[dict[str, Any]] = []
    for chunk in results:
        metadata = chunk.get("metadata") or {}
        chunk_model = metadata.get("embedding_model")
        if chunk_model is None:
            _record_embedding_provenance("unknown", current_model)
            filtered.append(chunk)
            continue
        if chunk_model != current_model:
            _record_embedding_provenance(chunk_model, current_model)
            logger.warning(
                "rag_embedding_mismatch chunk=%s current=%s strict=%s",
                chunk_model,
                current_model,
                strict_mode,
            )
            if strict_mode:
                continue
        filtered.append(chunk)
    return filtered


def _record_embedding_provenance(chunk_model: str, current_model: str) -> None:
    """Counter `rag_model_mismatch_total` для observability re-embed gap."""
    try:
        from src.backend.core.utils.metrics_registry import metrics_registry

        counter = metrics_registry.counter(
            "rag_model_mismatch_total",
            "Chunks с embedding_model != current rag_settings.embedding_model",
            labels=("chunk_model", "current_model"),
        )
        counter.labels(chunk_model=chunk_model, current_model=current_model).inc()
    except Exception as _:  # noqa: BLE001
        logger.debug("rag_model_mismatch metric emit failed", exc_info=True)


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
