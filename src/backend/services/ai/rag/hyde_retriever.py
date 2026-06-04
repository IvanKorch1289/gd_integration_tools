"""Block K4 W6 (wave:s19/k4-w6-adaptive-rag-strategy-finale): HyDE Retriever.

Hypothetical Document Embeddings (HyDE) — генерация гипотетического ответа
перед embedding search.

Ссылка: Gao et al. "Precise Zero-shot Dense Retrieval without Contradictory
Documents" (https://arxiv.org/abs/2312.04481).

HyDE-алгоритм:
1. Генерация LLM гипотетического документа (ideal answer) по запросу.
2. Embedding гипотетического документа.
3. Поиск по embedding гипотетического документа в vector store.
4. Возврат найденных реальных документов (не гипотетического).

Преимущество: гипотетический документ "запоминает" стиль и структуру
релевантных документов из обучающей выборки, что улучшает retrieval recall.

Использование::

    hyde = HyDERetriever(
        embed_fn=embedding_service.embed_texts,
        search_vectors=vector_store.search,
        generate_hypothetical=llm.generate_text,
    )
    results = await hyde.retrieve(query="кредитная политика", top_k=5)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict

__all__ = ("HyDEConfig", "HyDEResult", "HyDERetriever")

logger = logging.getLogger(__name__)

# Максимальная длина гипотетического документа в токенах.
DEFAULT_MAX_TOKENS_HYPOTHETICAL = 256


class HyDEResult(TypedDict):
    """Результат HyDE retrieval.

    Attributes:
        chunk_id: Уникальный идентификатор чанка.
        document: Текстовое содержание чанка.
        metadata: Метаданные (source, page, etc.).
        score: Similarity score [0..1].
        hypothetical_document: Сгенерированный гипотетический документ
            (для отладки и trace).
    """

    chunk_id: str
    document: str
    metadata: dict[str, Any]
    score: float
    hypothetical_document: str


@dataclass(frozen=True, slots=True)
class HyDEConfig:
    """Конфигурация HyDE retriever.

    Attributes:
        max_tokens: Максимальное количество токенов в гипотетическом
            документе.
        temperature: Temperature для генерации LLM (default 0.1 — нужен
            точный, не творческий ответ).
        prompt_template: Шаблон prompt для генерации гипотетического
            документа. ``{query}`` заменяется на реальный запрос.
        include_hypothetical_in_result: Включать гипотетический документ
            в результат (для debug/traces).
    """

    max_tokens: int = DEFAULT_MAX_TOKENS_HYPOTHETICAL
    temperature: float = 0.1
    prompt_template: str = (
        "Напиши краткий идеальный ответ на следующий вопрос. "
        "Отвечай только по существу, без введения. "
        "Вопрос: {query}"
    )
    include_hypothetical_in_result: bool = False


GenerateTextFn = Callable[[str, int, float], Awaitable[str]]


class HyDERetriever:
    """HyDE retriever: Hypothetical Document Embeddings.

    Args:
        embed_fn: Async callable ``(texts: list[str]) -> list[embeddings]``.
        search_vectors: Async callable
            ``(embeddings: list[list[float]], top_k: int) -> list[result_dict]``.
        generate_hypothetical: Async callable
            ``(prompt: str, max_tokens: int, temperature: float) -> str``.
            LLM для генерации гипотетического документа.
        config: HyDEConfig с настройками.
    """

    def __init__(
        self,
        embed_fn: Callable[[Sequence[str]], Awaitable[list[list[float]]]],
        search_vectors: Callable[
            [list[list[float]], int], Awaitable[list[dict[str, Any]]]
        ],
        generate_hypothetical: GenerateTextFn,
        *,
        config: HyDEConfig | None = None,
    ) -> None:
        self._embed_fn = embed_fn
        self._search_vectors = search_vectors
        self._generate_hypothetical = generate_hypothetical
        self._config = config or HyDEConfig()

    async def retrieve(self, query: str, top_k: int = 5) -> list[HyDEResult]:
        """HyDE retrieval по query.

        Алгоритм:
            1. generate_hypothetical(prompt, max_tokens, temperature) →
               hypothetical_doc.
            2. embed_fn([hypothetical_doc]) → hypothetical_embedding.
            3. search_vectors([hypothetical_embedding], top_k) → matched docs.
            4. Возврат matched docs + hypothetical_doc (опционально).

        Args:
            query: Текстовый запрос.
            top_k: Количество результатов.

        Returns:
            Список HyDEResult длиной ≤ top_k.
        """
        if not query.strip():
            return []

        # Шаг 1: генерация гипотетического документа.
        try:
            hypothetical_doc = await self._generate_hypothetical(
                prompt=self._config.prompt_template.format(query=query),
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
            )
        except Exception as exc:
            logger.warning("hyde_retriever.generate_failed: %s", exc)
            return []

        if not hypothetical_doc.strip():
            logger.warning("hyde_retriever.empty_hypothetical")
            return []

        # Шаг 2: embedding гипотетического документа.
        try:
            embeddings = await self._embed_fn([hypothetical_doc])
        except Exception as exc:
            logger.warning("hyde_retriever.embed_failed: %s", exc)
            return []

        if not embeddings or not embeddings[0]:
            logger.warning("hyde_retriever.empty_embedding")
            return []

        # Шаг 3: vector search.
        try:
            results = await self._search_vectors([embeddings[0]], top_k)
        except Exception as exc:
            logger.warning("hyde_retriever.search_failed: %s", exc)
            return []

        # Шаг 4: маппинг в HyDEResult.
        dense_results: list[HyDEResult] = []
        for doc in results[:top_k]:
            chunk_id = str(doc.get("id") or doc.get("metadata", {}).get("id") or "")
            dense_results.append(
                HyDEResult(
                    chunk_id=chunk_id,
                    document=str(doc.get("document") or doc.get("text") or ""),
                    metadata=dict(doc.get("metadata") or {}),
                    score=float(doc.get("score", 1.0)),
                    hypothetical_document=(
                        hypothetical_doc
                        if self._config.include_hypothetical_in_result
                        else ""
                    ),
                )
            )
        return dense_results
