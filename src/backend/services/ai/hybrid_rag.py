"""Hybrid RAG — BM25 + dense vector + cross-encoder reranking.

Улучшает recall на +20-30% vs vector-only через:
1. BM25 (lexical) — находит точные совпадения ключевых слов
2. Dense vector (semantic) — находит близкие по смыслу
3. Cross-encoder rerank — финальная оценка (query, document) pairs

Все компоненты опциональны:
- BM25 через rank_bm25 (или fallback: просто vector search)
- Cross-encoder через sentence-transformers (или fallback: rank by score)

Multi-instance safety:
- Vector store (Chroma/FAISS) — shared centralized storage
- BM25 index — per-instance rebuild из тех же документов
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ("HybridRAGSearch", "get_hybrid_rag")

logger = logging.getLogger("services.hybrid_rag")


class HybridRAGSearch:
    """Hybrid RAG: BM25 + vector + reranker.

    Делегирует векторный поиск в существующий RAGService.
    BM25 и reranker — опциональные улучшения поверх.
    """

    def __init__(self) -> None:
        self._rag: Any = None
        self._bm25: Any = None
        self._bm25_docs: list[dict[str, Any]] = []
        self._reranker: Any = None
        self._try_init()

    def _try_init(self) -> None:
        try:
            from rank_bm25 import BM25Okapi  # noqa: F401

            logger.debug("rank_bm25 available for hybrid search")
        except ImportError:
            logger.debug("rank_bm25 not installed, hybrid falls to vector-only")

        # IL-CRIT1.3 / ADR-014: sentence-transformers помечен deprecated.
        # `fastembed` не поставляет CrossEncoder как drop-in замену, поэтому
        # reranking отключён по умолчанию. Если заказчику нужен rerank —
        # установить opt-in: `pip install gd_integration_tools[rag-rerank]`
        # (extra добавляет `sentence-transformers`), либо дождаться IL-AI2
        # где будет использован BGE reranker через fastembed.
        try:
            from sentence_transformers import CrossEncoder  # noqa: PLC0415

            self._reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            logger.info("Cross-encoder reranker loaded (opt-in, deprecated path)")
        except ImportError:
            logger.debug(
                "sentence-transformers not installed — reranking disabled. "
                "Install gd_integration_tools[rag-rerank] for rerank support."
            )
            self._reranker = None
        except Exception as exc:  # noqa: BLE001
            logger.debug("Cross-encoder model load failed: %s", exc)
            self._reranker = None

    def _get_rag(self) -> Any:
        if self._rag is None:
            from src.backend.services.ai.rag_service import get_rag_service

            self._rag = get_rag_service()
        return self._rag

    def index_bm25(self, documents: list[dict[str, Any]]) -> None:
        """Создаёт BM25 индекс (in-memory, per-instance)."""
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            return

        tokenized = [
            str(doc.get("text", doc.get("document", ""))).lower().split()
            for doc in documents
        ]
        if not tokenized:
            return
        self._bm25 = BM25Okapi(tokenized)
        self._bm25_docs = documents

    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        namespace: str | None = None,
        alpha: float = 0.5,
        rerank: bool = True,
    ) -> list[dict[str, Any]]:
        """Hybrid search.

        Args:
            query: Поисковый запрос.
            top_k: Финальное количество результатов.
            namespace: Namespace vector store.
            alpha: Вес vector search (0.0=только BM25, 1.0=только vector).
            rerank: Применять cross-encoder reranking.

        Returns:
            Список документов {text, score, source: "vector"|"bm25"|"hybrid"}.
        """
        rag = self._get_rag()

        vector_results = await rag.search(
            query=query, top_k=top_k * 3, namespace=namespace
        )

        bm25_results: list[dict[str, Any]] = []
        if self._bm25 is not None and self._bm25_docs:
            try:
                tokenized_query = query.lower().split()
                scores = self._bm25.get_scores(tokenized_query)
                import numpy as np

                top_indices = np.argsort(scores)[::-1][: top_k * 3]
                bm25_results = [
                    {**self._bm25_docs[i], "score": float(scores[i]), "source": "bm25"}
                    for i in top_indices
                    if scores[i] > 0
                ]
            except Exception as exc:
                logger.warning("BM25 search failed: %s", exc)

        combined = self._combine_scores(vector_results, bm25_results, alpha=alpha)

        if rerank and self._reranker is not None and combined:
            combined = self._rerank(query, combined)

        return combined[:top_k]

    def _combine_scores(
        self, vector: list[dict[str, Any]], bm25: list[dict[str, Any]], *, alpha: float
    ) -> list[dict[str, Any]]:
        """Merge по document text с weighted scoring."""
        merged: dict[str, dict[str, Any]] = {}
        for doc in vector:
            key = str(doc.get("document", doc.get("text", "")))[:200]
            merged[key] = {
                **doc,
                "score": doc.get("score", 0.0) * alpha,
                "source": "vector",
            }
        for doc in bm25:
            key = str(doc.get("text", doc.get("document", "")))[:200]
            if key in merged:
                merged[key]["score"] += doc.get("score", 0.0) * (1 - alpha)
                merged[key]["source"] = "hybrid"
            else:
                merged[key] = {**doc, "score": doc.get("score", 0.0) * (1 - alpha)}
        return sorted(merged.values(), key=lambda x: x.get("score", 0), reverse=True)

    def _rerank(
        self, query: str, candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Cross-encoder rerank (query, doc) pairs."""
        try:
            pairs = [
                (query, str(doc.get("document", doc.get("text", ""))))
                for doc in candidates
            ]
            scores = self._reranker.predict(pairs)
            for doc, score in zip(candidates, scores):
                doc["rerank_score"] = float(score)
            return sorted(
                candidates, key=lambda x: x.get("rerank_score", 0), reverse=True
            )
        except Exception as exc:
            logger.warning("Rerank failed: %s", exc)
            return candidates


_instance: HybridRAGSearch | None = None


def get_hybrid_rag() -> HybridRAGSearch:
    global _instance
    if _instance is None:
        _instance = HybridRAGSearch()
    return _instance
