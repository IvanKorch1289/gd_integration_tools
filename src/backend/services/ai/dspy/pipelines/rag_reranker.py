"""rag_reranker DSPy-pipeline (K4 S6 W2).

Принимает (query, candidate_docs[]) и возвращает упорядоченный список
``doc_id``. Метрика — NDCG@k поверх expected ranking.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class _RagRerankerPipeline:
    name: str = "rag_reranker"
    description: str = "Reranker для RAG-кандидатов; metric=NDCG@k"

    def forward(self, example: dict[str, Any]) -> str:
        """Базовая heuristic: сортирует по token-overlap с query."""
        query = str(example.get("query") or "").lower()
        query_tokens = {t for t in query.split() if t}
        candidates = example.get("candidates") or []

        def _score(doc: dict[str, Any]) -> float:
            text = str(doc.get("text") or "").lower()
            doc_tokens = {t for t in text.split() if t}
            if not doc_tokens or not query_tokens:
                return 0.0
            return len(doc_tokens & query_tokens) / max(len(query_tokens), 1)

        ranked = sorted(candidates, key=_score, reverse=True)
        return json.dumps([d.get("id") for d in ranked], ensure_ascii=False)

    def metric(self, example: dict[str, Any], output: str) -> float:
        """NDCG@k где k = min(len(predicted), len(expected_ranking))."""
        try:
            predicted = json.loads(output)
        except Exception:  # noqa: BLE001
            return 0.0
        expected_ranking = example.get("expected_ranking") or []
        if not predicted or not expected_ranking:
            return 0.0

        gains = {doc_id: 1.0 / math.log2(rank + 2) for rank, doc_id in enumerate(expected_ranking)}
        dcg = sum(
            gains.get(doc_id, 0.0) / math.log2(rank + 2)
            for rank, doc_id in enumerate(predicted)
        )
        ideal = sum(
            (1.0 / math.log2(rank + 2)) ** 2
            for rank in range(min(len(predicted), len(expected_ranking)))
        )
        return dcg / ideal if ideal > 0 else 0.0


rag_reranker_pipeline = _RagRerankerPipeline()
__all__ = ("rag_reranker_pipeline",)
