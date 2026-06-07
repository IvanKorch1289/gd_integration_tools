"""Block K4 W6 (wave:s19/k4-w6-adaptive-rag-strategy-finale): Dense Retriever.

Standard vector embedding retrieval for RAG pipelines.

Использование::

    dense = DenseRetriever(
        embed_fn=embedding_service.embed_texts,
        vector_store=vector_store,
    )
    results = await dense.retrieve(query="кредитная политика", top_k=5)
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypedDict

__all__ = ("DenseResult", "DenseRetriever")

logger = get_logger(__name__)


class DenseResult(TypedDict):
    """Результат dense retrieval.

    Attributes:
        chunk_id: Уникальный идентификатор чанка.
        document: Текстовое содержание чанка.
        metadata: Метаданные (source, page, etc.).
        score: Similarity score [0..1].
    """

    chunk_id: str
    document: str
    metadata: dict[str, Any]
    score: float


EmbedFn = Callable[[Sequence[str]], Awaitable[list[list[float]]]]
SearchVectorsFn = Callable[[list[list[float]], int], Awaitable[list[dict[str, Any]]]]
SearchTextsFn = Callable[[str, int], Awaitable[list[dict[str, Any]]]]


class DenseRetriever:
    """Dense retriever: vector embeddings + similarity search.

    Args:
        embed_fn: Async callable ``(texts: list[str]) -> list[embeddings]``.
        search_vectors: Async callable
            ``(embeddings: list[list[float]], top_k: int) -> list[result_dict]``.
            Receives pre-computed query embedding and returns matched docs.
            Each result dict must contain ``id``, ``document``/``text``,
            ``metadata``, and optionally ``score``.
        chunk_id_field: Название поля в result dict для извлечения chunk_id.
            Default: ``"id"``. Также проверяется ``metadata.id``.
        default_score: Score используется если vector store не возвращает score.
    """

    def __init__(
        self,
        embed_fn: EmbedFn,
        search_vectors: SearchVectorsFn,
        *,
        chunk_id_field: str = "id",
        default_score: float = 1.0,
    ) -> None:
        self._embed_fn = embed_fn
        self._search_vectors = search_vectors
        self._chunk_id_field = chunk_id_field
        self._default_score = default_score

    async def retrieve(self, query: str, top_k: int = 5) -> list[DenseResult]:
        """Dense retrieval по query.

        Алгоритм:
            1. embed_fn([query]) → query_embedding.
            2. search_vectors([query_embedding], top_k) → matched docs.
            3. Маппинг в DenseResult.

        Args:
            query: Текстовый запрос.
            top_k: Количество результатов.

        Returns:
            Список DenseResult длиной ≤ top_k.
        """
        if not query.strip():
            return []

        try:
            embeddings = await self._embed_fn([query])
        except Exception as exc:
            logger.warning("dense_retriever.embed_failed: %s", exc)
            return []

        if not embeddings or not embeddings[0]:
            logger.warning("dense_retriever.empty_embedding")
            return []

        try:
            results = await self._search_vectors([embeddings[0]], top_k)
        except Exception as exc:
            logger.warning("dense_retriever.search_failed: %s", exc)
            return []

        return [self._to_dense_result(doc) for doc in results[:top_k]]

    def _to_dense_result(self, doc: dict[str, Any]) -> DenseResult:
        """Преобразует result dict → DenseResult."""
        chunk_id = str(
            doc.get(self._chunk_id_field)
            or doc.get("metadata", {}).get(self._chunk_id_field)
            or ""
        )
        return DenseResult(
            chunk_id=chunk_id,
            document=str(doc.get("document") or doc.get("text") or ""),
            metadata=dict(doc.get("metadata") or {}),
            score=float(doc.get("score", self._default_score)),
        )
