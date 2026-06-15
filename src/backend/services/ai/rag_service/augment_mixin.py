from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING

from src.backend.services.ai.rag_augment import AugmentResult, build_augment_result
from src.backend.services.ai.rag_service.search_mixin import (
    _format_context_with_sources,
)
from src.backend.services.ai.rag_service.state import RAGCitation

if TYPE_CHECKING:  # pragma: no cover
    pass


class AugmentMixin:
    """prompt augmentation (3 augment variants) для RAGService. S64 W4 extraction."""

    __slots__ = ()

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
            except Exception as exc:
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
