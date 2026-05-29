"""RerankerProcessor — cross-encoder reranking for RAG pipelines.

Integrates into the RAG pipeline: initial retrieval → cross-encoder rerank → return top-k.
Uses feature flag ``reranking_pipeline_enabled`` (default-OFF).

Model: cross-encoder/ms-marco-MiniLM-L-12-v2 (HuggingFace).

Sprint 19 K4 W2: latency budget tracking — model.predict() is timed and stored in
``rerank_latency_ms`` exchange property; if it exceeds ``latency_budget_ms``
(default 50 ms) a warning is logged and the budget is recorded in
``rerank_budget_exceeded``.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    pass

__all__ = ("RerankerProcessor",)

logger = logging.getLogger("dsl.ai.reranker")


class RerankerProcessor(BaseProcessor):
    """Cross-encoder reranking processor for RAG retrieval results.

    Takes initial retrieval candidates (from ``input_property``), re-ranks them
    using a cross-encoder model scoring (query, document) pairs, and stores
    the top-k results in ``output_property``.

    The cross-encoder model is loaded lazily on first use from HuggingFace:
    ``cross-encoder/ms-marco-MiniLM-L-12-v2``.

    Usage in DSL::

        .rerank(input_property="vector_results", output_property="reranked_results", top_k=5)

    Or as part of a RAG pipeline::

        .rag_query(top_k=20)          # Initial retrieval (broad)
        .rerank(top_k=5)              # Cross-encoder rerank (precise)

    Args:
        input_property: Exchange property containing initial retrieval candidates.
            Expected format: list[dict] where each dict has at least ``text`` or
            ``document`` key with document content. Default: ``vector_results``.
        output_property: Exchange property to store reranked results.
            Default: ``reranked_results``.
        query_field: Key in exchange body dict to extract query string.
            Default: ``question``.
        top_k: Number of top results to return after reranking. Default: 5.
        name: Optional processor name for logging.
    """

    def __init__(
        self,
        input_property: str = "vector_results",
        output_property: str = "reranked_results",
        query_field: str = "question",
        top_k: int = 5,
        latency_budget_ms: float = 50.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "reranker")
        self._input_property = input_property
        self._output_property = output_property
        self._query_field = query_field
        self._top_k = top_k
        self._latency_budget_ms = latency_budget_ms
        self._model: Any = None
        self._model_name: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Process reranking: retrieve candidates → cross-encoder score → top-k."""
        from src.backend.core.config.features import feature_flags

        # Feature flag check — bypass reranking if disabled
        if not feature_flags.reranking_pipeline_enabled:
            logger.debug("Reranking disabled via feature flag, skipping")
            exchange.set_property(self._output_property, [])
            return

        # Extract query from body
        body = exchange.in_message.body
        if isinstance(body, dict):
            query = body.get(self._query_field, "")
        else:
            query = str(body) if body else ""
        if not query:
            logger.warning("RerankerProcessor: empty query, returning empty results")
            exchange.set_property(self._output_property, [])
            return

        # Extract candidates from input property
        candidates = exchange.properties.get(self._input_property, [])
        if not candidates:
            logger.debug("RerankerProcessor: no candidates in %s", self._input_property)
            exchange.set_property(self._output_property, [])
            return
        if not isinstance(candidates, list):
            logger.warning(
                "RerankerProcessor: expected list in %s, got %s",
                self._input_property,
                type(candidates).__name__,
            )
            exchange.set_property(self._output_property, [])
            return

        # Lazy-load cross-encoder model
        model = self._get_model()
        if model is None:
            logger.warning("RerankerProcessor: model unavailable, returning candidates as-is")
            exchange.set_property(self._output_property, candidates[: self._top_k])
            return

        # Build (query, document) pairs for cross-encoder
        pairs = [
            (query, str(doc.get("document") or doc.get("text") or ""))
            for doc in candidates
        ]

        # Sprint 19 K4 W2: latency budget tracking
        t0 = time.perf_counter()
        try:
            scores = model.predict(pairs)
            if not isinstance(scores, list):
                scores = [scores]
        except Exception as exc:  # noqa: BLE001
            logger.warning("RerankerProcessor: model.predict failed: %s", exc)
            exchange.set_property(self._output_property, candidates[: self._top_k])
            return
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # Store latency metrics
        exchange.set_property("rerank_latency_ms", round(elapsed_ms, 2))
        budget_exceeded = elapsed_ms > self._latency_budget_ms
        exchange.set_property("rerank_budget_exceeded", budget_exceeded)
        if budget_exceeded:
            logger.warning(
                "RerankerProcessor: latency %.1f ms exceeds budget %.1f ms "
                "(%d candidates, top_k=%d)",
                elapsed_ms,
                self._latency_budget_ms,
                len(candidates),
                self._top_k,
            )

        # Attach rerank scores and sort
        for doc, score in zip(candidates, scores, strict=True):
            doc["rerank_score"] = float(score)

        reranked = sorted(
            candidates,
            key=lambda d: d.get("rerank_score", 0.0),
            reverse=True,
        )

        exchange.set_property(self._output_property, reranked[: self._top_k])
        logger.info(
            "RerankerProcessor: reranked %d candidates → top-%d",
            len(candidates),
            self._top_k,
        )

    def _get_model(self) -> Any:
        """Lazy-load cross-encoder model (singleton pattern)."""
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import CrossEncoder  # noqa: PLC0415

            self._model = CrossEncoder(self._model_name)
            logger.info("RerankerProcessor: loaded cross-encoder model %s", self._model_name)
            return self._model
        except ImportError:
            logger.warning(
                "RerankerProcessor: sentence-transformers not installed. "
                "Install: pip install sentence-transformers"
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("RerankerProcessor: failed to load model %s: %s", self._model_name, exc)
            return None

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._input_property != "vector_results":
            spec["input_property"] = self._input_property
        if self._output_property != "reranked_results":
            spec["output_property"] = self._output_property
        if self._query_field != "question":
            spec["query_field"] = self._query_field
        if self._top_k != 5:
            spec["top_k"] = self._top_k
        if self._latency_budget_ms != 50.0:
            spec["latency_budget_ms"] = self._latency_budget_ms
        return {"rerank": spec}
