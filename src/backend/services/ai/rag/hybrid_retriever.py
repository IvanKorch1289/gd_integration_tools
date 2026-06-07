"""Block 3.2 (gap-ai-3.2, ADR-0074): Hybrid Retriever (dense + BM25 + RRF).

Объединяет два независимых retrieval-backend через Reciprocal Rank Fusion:

* **dense** — семантический поиск через embeddings (vector store, Qdrant/Chroma);
* **BM25** — лексический keyword-поиск через ``rank-bm25`` (lazy-import).
* **RRF** — Reciprocal Rank Fusion: ``score = Σ 1/(k + rank_i)`` по каждому
  rank-листу. k=60 — стандартное значение (Cormack et al. 2009).

Lazy-import:
    ``rank-bm25`` подключается через extra ``[rag-advanced]``. При
    отсутствии пакета :class:`HybridRetriever` graceful fallback на
    dense-only (counter ``rag_hybrid_fallback_total`` инкрементируется).

Use case:
    Запрос "ИНН 7707083893 кредитная политика" содержит lexical match
    ("7707083893") и semantic match ("кредитная политика"). Dense-only
    может пропустить ИНН (если не в embedding пространстве), BM25-only
    пропустит семантические синонимы политики. RRF комбинирует оба.
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ("HybridRetriever", "rrf_merge")

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class HybridResult:
    """Результат hybrid retrieval — chunk + rrf_score + provenance (dense / bm25 / both)."""

    chunk_id: str
    document: str
    metadata: dict[str, Any]
    rrf_score: float
    sources: tuple[str, ...]


class HybridRetriever:
    """Block 3.2: dense + BM25 + RRF retriever поверх vector store.

    Args:
        dense_search: Async callable ``(query, top_k) → list[chunk_dict]``
            от vector store (e.g. RAGService.search).
        corpus: Список ``{"id": str, "text": str, "metadata": dict}`` для
            BM25 индексации. При пустом списке — fallback на dense-only.
            Для multi-instance production используйте ``corpus_loader`` (см. ниже).
        rrf_k: Параметр RRF (default 60).
        corpus_loader: Async callable ``() → list[dict]``. Если задан,
            ``corpus`` игнорируется и BM25-индекс перестраивается при каждом
            вызове ``reload()`` из corpus_loader. Используйте для загрузки
            corpus из Redis (shared across instances) в multi-instance deployment.
    """

    def __init__(
        self,
        *,
        dense_search: Any,
        corpus: Sequence[dict[str, Any]] | None = None,
        rrf_k: int = 60,
        corpus_loader: Any = None,  # async callable, returns list[dict]
    ) -> None:
        self._dense_search = dense_search
        self._corpus = list(corpus or [])
        self._rrf_k = max(1, int(rrf_k))
        self._bm25: Any = None
        self._bm25_unavailable = not self._corpus
        self._corpus_loader = corpus_loader  # async callable for Redis-backed corpus

    async def reload(self) -> None:
        """Перезагрузить corpus из corpus_loader и перестроить BM25-индекс.

        Вызывайте после обновления corpus в backend store (Redis / DB / S3).
        В multi-instance deployment каждый инстанс вызывает reload() при
        получении события обновления (Redis pub/sub, Kafka message и т.д.).
        """
        if self._corpus_loader is None:
            return
        try:
            new_corpus = await self._corpus_loader()
            self._corpus = list(new_corpus or [])
            self._bm25 = None  # force rebuild on next _ensure_bm25()
            self._bm25_unavailable = not self._corpus
        except Exception as exc:
            logger.warning("hybrid_retriever.corpus_loader_failed: %s", exc)

    def _ensure_bm25(self) -> Any:
        """Lazy-init BM25Okapi на первом вызове.

        Возвращает ``None`` при ImportError ``rank-bm25`` либо пустом corpus.
        """
        if self._bm25_unavailable:
            return None
        if self._bm25 is not None:
            return self._bm25
        try:
            from rank_bm25 import BM25Okapi
        except ImportError as exc:
            logger.warning(
                "rank-bm25 не установлен (extra '[rag-advanced]'), "
                "fallback на dense-only: %s",
                exc,
            )
            _record_hybrid_fallback(reason="bm25_import_error")
            self._bm25_unavailable = True
            return None

        try:
            tokenized = [_tokenize(doc.get("text") or "") for doc in self._corpus]
            self._bm25 = BM25Okapi(tokenized)
            return self._bm25
        except Exception as exc:
            logger.warning("BM25Okapi init failed (%s), dense-only", exc)
            _record_hybrid_fallback(reason="bm25_init_error")
            self._bm25_unavailable = True
            return None

    async def retrieve(self, *, query: str, top_k: int = 5) -> list[HybridResult]:
        """Hybrid retrieval с RRF-merge.

        Алгоритм:
            1. dense_search(query, top_k*2) → dense_results;
            2. BM25.get_top_n(tokenized_query, corpus, n=top_k*2) → bm25_results;
            3. rrf_merge({dense, bm25}, k=rrf_k) → top_k финальный список.

        При недоступности BM25 — passthrough dense.

        Returns:
            Список :class:`HybridResult` длиной ≤ top_k.
        """
        # Получить dense выборку (×2 для diversity при RRF-merge).
        try:
            dense_raw = await self._dense_search(query=query, top_k=top_k * 2)
        except TypeError:
            # Backward-compat для search(query, top_k) сигнатуры без kw-args.
            dense_raw = await self._dense_search(query, top_k * 2)
        except Exception as exc:
            logger.warning("hybrid_retriever.dense_failed: %s", exc)
            _record_hybrid_fallback(reason="dense_error")
            dense_raw = []
        dense_chunks = list(dense_raw or [])

        # BM25 retrieval (если доступен и corpus непустой).
        bm25 = self._ensure_bm25()
        bm25_chunks: list[dict[str, Any]] = []
        if bm25 is not None and self._corpus:
            try:
                query_tokens = _tokenize(query)
                scored = bm25.get_top_n(query_tokens, self._corpus, n=top_k * 2)
                bm25_chunks = list(scored)
            except Exception as exc:
                logger.warning("hybrid_retriever.bm25_runtime_failed: %s", exc)
                _record_hybrid_fallback(reason="bm25_runtime_error")

        if not bm25_chunks:
            # Fallback на dense-only.
            return [
                _to_hybrid_result(c, rrf_score=1.0, sources=("dense",))
                for c in dense_chunks[:top_k]
            ]

        merged = rrf_merge(
            ranked_lists=[
                ("dense", [_chunk_id(c) for c in dense_chunks]),
                ("bm25", [_chunk_id(c) for c in bm25_chunks]),
            ],
            k=self._rrf_k,
        )
        # Восстановить chunks по id (dict-lookup для O(1)).
        chunk_by_id: dict[str, dict[str, Any]] = {}
        for c in (*dense_chunks, *bm25_chunks):
            cid = _chunk_id(c)
            chunk_by_id.setdefault(cid, c)
        results: list[HybridResult] = []
        for chunk_id, rrf_score, sources in merged[:top_k]:
            chunk = chunk_by_id.get(chunk_id)
            if chunk is None:
                continue
            results.append(
                _to_hybrid_result(chunk, rrf_score=rrf_score, sources=sources)
            )
        return results


def rrf_merge(
    *, ranked_lists: list[tuple[str, list[str]]], k: int = 60
) -> list[tuple[str, float, tuple[str, ...]]]:
    """Reciprocal Rank Fusion: merge ranked lists в единый список.

    Формула: ``score(doc) = Σ_lists 1/(k + rank_in_list)``.

    Args:
        ranked_lists: Кортежи ``(source_name, [chunk_id, ...])``,
            где order = ranking.
        k: Параметр RRF (default 60).

    Returns:
        Список ``(chunk_id, rrf_score, sources_tuple)`` отсортированный
        по убыванию rrf_score.
    """
    scores: dict[str, float] = {}
    provenance: dict[str, set[str]] = {}
    for source, ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked):
            inc = 1.0 / (k + rank + 1)  # rank 0-based → +1 чтобы избежать /k
            scores[chunk_id] = scores.get(chunk_id, 0.0) + inc
            provenance.setdefault(chunk_id, set()).add(source)
    return sorted(
        ((cid, score, tuple(sorted(provenance[cid]))) for cid, score in scores.items()),
        key=lambda triple: triple[1],
        reverse=True,
    )


def _tokenize(text: str) -> list[str]:
    """Простой whitespace + lowercase tokenizer для BM25.

    Production-replacement: nltk / spaCy ru tokenizer + удаление stopwords.
    В scaffold-версии достаточно базовой логики.
    """
    return [t for t in text.lower().split() if t]


def _chunk_id(chunk: dict[str, Any]) -> str:
    """Извлекает chunk-id из dict (id или metadata.id)."""
    return str(chunk.get("id") or (chunk.get("metadata") or {}).get("id") or "")


def _to_hybrid_result(
    chunk: dict[str, Any], *, rrf_score: float, sources: tuple[str, ...]
) -> HybridResult:
    """Преобразует chunk dict → :class:`HybridResult`."""
    return HybridResult(
        chunk_id=_chunk_id(chunk),
        document=str(chunk.get("document") or chunk.get("text") or ""),
        metadata=dict(chunk.get("metadata") or {}),
        rrf_score=rrf_score,
        sources=sources,
    )


def _record_hybrid_fallback(*, reason: str) -> None:
    """Counter ``rag_hybrid_fallback_total`` через metrics_registry."""
    try:
        from src.backend.core.utils.metrics_registry import metrics_registry

        counter = metrics_registry.counter(
            "rag_hybrid_fallback_total",
            "Fallback на dense-only при недоступности BM25",
            labels=("reason",),
        )
        counter.labels(reason=reason).inc()
    except Exception as _:
        logger.debug("rag_hybrid_fallback metric emit failed", exc_info=True)
