"""Block K4 W6 (wave:s19/k4-w6-adaptive-rag-strategy-finale): Multi-Query Retriever.

Query expansion: генерация нескольких альтернативных формулировок запроса
и объединение результатов через RRF.

Ссылка: Buckley et al. "Retrieval System Effect" и Query Expansion via
Multiple Query Reformulations.

Multi-query-алгоритм:
1. Генерация N альтернативных запросов из оригинального.
2. Параллельный retrieval по каждому альтернативному запросу.
3. RRF-объединение всех rank-lists в финальный top-k.

Преимущество: покрытие разных аспектов запроса, снижение miss из-за
terminology mismatch.

Использование::

    multi = MultiQueryRetriever(
        embed_fn=embedding_service.embed_texts,
        search_vectors=vector_store.search,
        generate_reformulations=llm.generate_reformulations,
        num_queries=5,
    )
    results = await multi.retrieve(query="кредитная политика", top_k=5)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict

from src.backend.infrastructure.logging.factory import get_logger
from src.backend.services.ai.rag.hybrid_retriever import rrf_merge

__all__ = ("MultiQueryConfig", "MultiQueryResult", "MultiQueryRetriever")

logger = get_logger(__name__)

DEFAULT_NUM_REFORMULATIONS = 5
DEFAULT_RRF_K = 60


class MultiQueryResult(TypedDict):
    """Результат multi-query retrieval.

    Attributes:
        chunk_id: Уникальный идентификатор чанка.
        document: Текстовое содержание чанка.
        metadata: Метаданные (source, page, etc.).
        score: RRF score после объединения.
        sources: Список запросов, которые вернули этот документ
            (для отладки).
    """

    chunk_id: str
    document: str
    metadata: dict[str, Any]
    score: float
    sources: list[str]


@dataclass(frozen=True, slots=True)
class MultiQueryConfig:
    """Конфигурация multi-query retriever.

    Attributes:
        num_reformulations: Количество альтернативных запросов для генерации.
            Default: 5.
        rrf_k: Параметр RRF (default 60).
        prompt_template: Шаблон prompt для генерации реформализаций.
            ``{query}`` заменяется на оригинальный запрос,
            ``{n}`` заменяется на num_reformulations.
        parallel: Выполнять retrieval параллельно (default True).
    """

    num_reformulations: int = DEFAULT_NUM_REFORMULATIONS
    rrf_k: int = DEFAULT_RRF_K
    prompt_template: str = (
        "Переформулируй следующий запрос {n} различными способами. "
        "Каждая реформализация должна раскрывать разный аспект или "
        "использовать синонимы. Верни только список реформализаций, "
        "по одной на строку. Оригинальный запрос: {query}"
    )
    parallel: bool = True


GenerateReformulationsFn = Callable[[str, int], Awaitable[list[str]]]


class MultiQueryRetriever:
    """Multi-query retriever: query expansion + RRF merge.

    Args:
        embed_fn: Async callable ``(texts: list[str]) -> list[embeddings]``.
        search_vectors: Async callable
            ``(embeddings: list[list[float]], top_k: int) -> list[result_dict]``.
        generate_reformulations: Async callable
            ``(query: str, num: int) -> list[str]``.
            Генерирует альтернативные формулировки запроса.
        config: MultiQueryConfig с настройками.
    """

    def __init__(
        self,
        embed_fn: Callable[[Sequence[str]], Awaitable[list[list[float]]]],
        search_vectors: Callable[
            [list[list[float]], int], Awaitable[list[dict[str, Any]]]
        ],
        generate_reformulations: GenerateReformulationsFn,
        *,
        config: MultiQueryConfig | None = None,
    ) -> None:
        self._embed_fn = embed_fn
        self._search_vectors = search_vectors
        self._generate_reformulations = generate_reformulations
        self._config = config or MultiQueryConfig()

    async def retrieve(self, query: str, top_k: int = 5) -> list[MultiQueryResult]:
        """Multi-query retrieval по query.

        Алгоритм:
            1. generate_reformulations(query, n) → list[alternative_queries].
            2. embed_fn(all_queries) → embeddings для всех запросов.
            3. Параллельный/последовательный search_vectors для каждого embedding.
            4. rrf_merge всех rank-lists → финальный top-k.

        Args:
            query: Текстовый запрос.
            top_k: Количество результатов.

        Returns:
            Список MultiQueryResult длиной ≤ top_k.
        """
        if not query.strip():
            return []

        # Шаг 1: генерация альтернативных запросов.
        try:
            reformulations = await self._generate_reformulations(
                query, self._config.num_reformulations
            )
        except Exception as exc:
            logger.warning("multi_query.generate_reformulations_failed: %s", exc)
            return []

        # Всегда включаем оригинальный запрос.
        all_queries = [query] + reformulations
        source_labels = ["original"] + [
            f"reform_{i}" for i in range(len(reformulations))
        ]

        # Шаг 2: embedding всех запросов.
        try:
            all_embeddings = await self._embed_fn(all_queries)
        except Exception as exc:
            logger.warning("multi_query.embed_failed: %s", exc)
            return []

        if not all_embeddings:
            logger.warning("multi_query.empty_embeddings")
            return []

        # Шаг 3: retrieval для каждого запроса.
        ranked_lists: list[tuple[str, list[str]]] = []
        chunks_by_id: dict[str, dict[str, Any]] = {}

        if self._config.parallel:
            import asyncio

            async def search_single(
                emb: list[float], label: str
            ) -> tuple[str, list[str]]:
                try:
                    results = await self._search_vectors([emb], top_k * 2)
                    chunk_ids = [self._chunk_id(doc) for doc in results]
                    for doc in results:
                        cid = self._chunk_id(doc)
                        if cid:
                            chunks_by_id.setdefault(cid, doc)
                    return label, chunk_ids
                except Exception as exc:
                    logger.warning("multi_query.search_failed for %s: %s", label, exc)
                    return label, []

            search_results = await asyncio.gather(
                *(
                    search_single(emb, label)
                    for emb, label in zip(all_embeddings, source_labels)
                )
            )
            ranked_lists = list(search_results)
        else:
            for emb, label in zip(all_embeddings, source_labels):
                try:
                    search_results = await self._search_vectors([emb], top_k * 2)
                    chunk_ids = [self._chunk_id(doc) for doc in search_results]
                    for doc in search_results:
                        cid = self._chunk_id(doc)
                        if cid:
                            chunks_by_id.setdefault(cid, doc)
                    ranked_lists.append((label, chunk_ids))
                except Exception as exc:
                    logger.warning("multi_query.search_failed for %s: %s", label, exc)

        if not ranked_lists:
            return []

        # Шаг 4: RRF merge.
        merged = rrf_merge(ranked_lists=ranked_lists, k=self._config.rrf_k)

        # Шаг 5: маппинг в MultiQueryResult.
        final_results: list[MultiQueryResult] = []
        for chunk_id, rrf_score, sources in merged[:top_k]:
            chunk_doc: dict[str, Any] | None = chunks_by_id.get(chunk_id)
            if chunk_doc is None:
                continue
            final_results.append(
                MultiQueryResult(
                    chunk_id=chunk_id,
                    document=str(
                        chunk_doc.get("document") or chunk_doc.get("text") or ""
                    ),
                    metadata=dict(chunk_doc.get("metadata") or {}),
                    score=rrf_score,
                    sources=list(sources),
                )
            )
        return final_results

    def _chunk_id(self, doc: dict[str, Any]) -> str:
        """Извлекает chunk-id из dict."""
        return str(doc.get("id") or doc.get("metadata", {}).get("id") or "")
