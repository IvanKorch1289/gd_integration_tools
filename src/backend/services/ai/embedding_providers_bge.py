"""BGE-M3 (1024-dim dense) + bge-reranker-v2-m3 (cross-encoder).

Параллельный модуль к :mod:`services.ai.embedding_providers` — НЕ правит
существующую фабрику ``get_embedding_provider``. Регистрация выполняется
через :class:`EmbeddingProviderRegistry` (см. ``embedding_registry.py``).

Lazy-загрузка ``BGEM3FlagModel`` и ``FlagReranker`` — модели ~2.3GB
докачаются HF при первом запросе. Default-OFF (BGE_ENABLED=false).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("BGEM3EmbeddingProvider", "BGERerankerV2M3", "BGEUnavailable")


class BGEUnavailable(RuntimeError):
    """FlagEmbedding не установлен или модель не доступна."""


class BGEM3EmbeddingProvider:
    """Dense-эмбеддинги (1024-dim) через ``BGEM3FlagModel.encode``."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        cache_dir: str | None = None,
        use_fp16: bool = True,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._use_fp16 = use_fp16
        self._model: Any = None

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-not-found]
        except ImportError as exc:
            raise BGEUnavailable(
                "FlagEmbedding не установлен — добавьте extra '[ai-2026]'."
            ) from exc
        self._model = BGEM3FlagModel(
            self._model_name, cache_dir=self._cache_dir, use_fp16=self._use_fp16
        )
        logger.info(
            "BGEM3FlagModel %r loaded (cache=%s)", self._model_name, self._cache_dir
        )
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Возвращает dense-векторы (1024-dim) batch'ом."""
        if not texts:
            return []

        def _encode() -> list[list[float]]:
            model = self._ensure_model()
            output = model.encode(texts, return_dense=True, return_sparse=False)
            dense = output["dense_vecs"] if isinstance(output, dict) else output
            return [list(v) for v in dense]

        return await asyncio.to_thread(_encode)


class BGERerankerV2M3:
    """Cross-encoder reranker через ``FlagReranker`` (bge-reranker-v2-m3)."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        cache_dir: str | None = None,
        use_fp16: bool = True,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._use_fp16 = use_fp16
        self._model: Any = None

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from FlagEmbedding import FlagReranker  # type: ignore[import-not-found]
        except ImportError as exc:
            raise BGEUnavailable(
                "FlagEmbedding не установлен — добавьте extra '[ai-2026]'."
            ) from exc
        self._model = FlagReranker(
            self._model_name, cache_dir=self._cache_dir, use_fp16=self._use_fp16
        )
        return self._model

    async def rerank(self, query: str, documents: list[str]) -> list[tuple[str, float]]:
        """Возвращает документы с relevance-score, отсортированные DESC."""
        if not documents:
            return []

        pairs = [[query, doc] for doc in documents]

        def _score() -> list[float]:
            model = self._ensure_model()
            scores = model.compute_score(pairs, normalize=True)
            if isinstance(scores, (int, float)):
                return [float(scores)]
            return [float(s) for s in scores]

        scores = await asyncio.to_thread(_score)
        return sorted(zip(documents, scores), key=lambda x: x[1], reverse=True)
