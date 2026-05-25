"""rag_reranker DSPy-pipeline (K4 S6 W2, Block 3.1 ADR-0074).

Принимает (query, candidate_docs[]) и возвращает упорядоченный список
``doc_id``. Метрика — NDCG@k поверх expected ranking.

Block 3.1 (gap-ai-3.1) реализация:
    * При ``BGESettings.reranker_enabled=True`` (default-OFF) использует
      :class:`FlagEmbedding.FlagReranker` с моделью ``BAAI/bge-reranker-v2-m3``
      (cross-encoder, multilingual: ru/en/zh+).
    * При выключенном flag, ImportError ``FlagEmbedding`` или CUDA OOM —
      graceful fallback на token-overlap heuristic (legacy).
    * Singleton-fingerprint reranker: модель загружается один раз на
      первом запросе и хранится в module-level кэше (lazy-init pattern).

Метрика наблюдаемости: counter ``rag_reranker_fallback_total{reason}``
инкрементируется при каждом fallback на token-overlap (для алертов на
утрату cross-encoder покрытия в production).
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from typing import Any

__all__ = ("rag_reranker_pipeline",)

logger = logging.getLogger("services.ai.dspy.rag_reranker")

_reranker_cache: Any = None
_reranker_unavailable: bool = False


def _resolve_bge_reranker() -> Any:
    """Lazy-init :class:`FlagReranker` с graceful fallback.

    Возвращает ``None`` если ``BGESettings.reranker_enabled=False`` либо
    модель/пакет недоступны. Кэш на module-level — модель грузится один раз.
    """
    global _reranker_cache, _reranker_unavailable
    if _reranker_unavailable:
        return None
    if _reranker_cache is not None:
        return _reranker_cache

    try:
        from src.backend.core.config.ai_2026 import bge_settings
    except Exception:  # noqa: BLE001
        _reranker_unavailable = True
        return None
    if not getattr(bge_settings, "reranker_enabled", False):
        _reranker_unavailable = True
        return None

    try:
        from FlagEmbedding import FlagReranker  # type: ignore[import-not-found]
    except ImportError as exc:
        logger.warning(
            "FlagEmbedding не установлен (extra '[rag-advanced]'), "
            "fallback на token-overlap: %s",
            exc,
        )
        _record_reranker_fallback(reason="import_error")
        _reranker_unavailable = True
        return None

    try:
        _reranker_cache = FlagReranker(
            getattr(bge_settings, "reranker_model", "BAAI/bge-reranker-v2-m3"),
            use_fp16=getattr(bge_settings, "reranker_use_fp16", True),
        )
        logger.info(
            "FlagReranker инициализирован: %s (fp16=%s)",
            getattr(bge_settings, "reranker_model", "BAAI/bge-reranker-v2-m3"),
            getattr(bge_settings, "reranker_use_fp16", True),
        )
        return _reranker_cache
    except Exception as exc:  # noqa: BLE001 — CUDA OOM / weights download fail
        logger.warning(
            "FlagReranker init failed (%s), fallback на token-overlap", exc
        )
        _record_reranker_fallback(reason="init_error")
        _reranker_unavailable = True
        return None


def _record_reranker_fallback(*, reason: str) -> None:
    """Counter ``rag_reranker_fallback_total`` для observability fallback."""
    try:
        from src.backend.infrastructure.observability.metrics_registry import (
            metrics_registry,
        )

        counter = metrics_registry.counter(
            "rag_reranker_fallback_total",
            "Fallback на token-overlap reranker при недоступности BGE",
            labels=("reason",),
        )
        counter.labels(reason=reason).inc()
    except Exception:  # noqa: BLE001
        logger.debug("rag_reranker_fallback metric emit failed", exc_info=True)


@dataclass(frozen=True, slots=True)
class _RagRerankerPipeline:
    name: str = "rag_reranker"
    description: str = (
        "Reranker для RAG-кандидатов; BGE cross-encoder (default) либо "
        "token-overlap fallback; metric=NDCG@k"
    )

    def forward(self, example: dict[str, Any]) -> str:
        """Block 3.1: rerank через BGE cross-encoder при доступности, иначе fallback.

        Сценарий BGE:
            * ``FlagReranker.compute_score([(query, doc_text) for doc in docs])``
              возвращает list[float] релевантностей.
            * Сортировка по убыванию score.

        Сценарий fallback (token-overlap):
            * Жаккара по токенам query ∩ doc_tokens.
        """
        query = str(example.get("query") or "")
        candidates = example.get("candidates") or []
        if not query or not candidates:
            return json.dumps(
                [d.get("id") for d in candidates], ensure_ascii=False
            )

        reranker = _resolve_bge_reranker()
        if reranker is not None:
            try:
                pairs = [(query, str(doc.get("text") or "")) for doc in candidates]
                scores = reranker.compute_score(pairs)
                if not isinstance(scores, list):
                    scores = [scores]
                ranked = sorted(
                    zip(candidates, scores, strict=True),
                    key=lambda pair: pair[1],
                    reverse=True,
                )
                return json.dumps(
                    [doc.get("id") for doc, _ in ranked], ensure_ascii=False
                )
            except Exception as exc:  # noqa: BLE001 — CUDA OOM/runtime
                logger.warning(
                    "FlagReranker.compute_score failed (%s), fallback на token-overlap",
                    exc,
                )
                _record_reranker_fallback(reason="runtime_error")
                # falls through to token-overlap below

        query_lower = query.lower()
        query_tokens = {t for t in query_lower.split() if t}

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

        gains = {
            doc_id: 1.0 / math.log2(rank + 2)
            for rank, doc_id in enumerate(expected_ranking)
        }
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
