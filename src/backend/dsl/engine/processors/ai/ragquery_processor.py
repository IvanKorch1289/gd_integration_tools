"""Auto-generated from ai_processors.py — single processor files."""

from __future__ import annotations

from typing import Any, Callable

import orjson

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

# Допустимые стратегии retrieval для :class:`RagQueryProcessor`.
# ``dense`` — стандартный k-NN; остальные обрабатываются downstream
# retriever'ом (см. RAG plan S11 K3) и активируются по namespace-config.
_RAG_STRATEGIES: tuple[str, ...] = (
    "dense",
    "hybrid",
    "hyde",
    "multi_query",
    "adaptive",
)


class RagQueryProcessor(BaseProcessor):
    """Structured RAG query с freshness-фильтрацией (Sprint 9 K4 W3).

    В отличие от :class:`VectorSearchProcessor` (raw vectors), возвращает
    :class:`AugmentResult` с метаданными по freshness и worst_freshness
    для UI-badge или branch-logic.

    S11 K3 W3: добавлен параметр ``strategy`` — outbound-сигнал для
    retriever'а о желаемой стратегии (``dense``/``hybrid``/``hyde``/
    ``multi_query``). Стратегия пишется в exchange property
    ``rag_strategy`` и в ``augment_result["strategy"]``, чтобы
    downstream-консьюмер мог веткой обработать результат разной
    природы (raw vectors vs lexical+semantic union).

    Usage::

        .rag_query(
            query_field="question",
            top_k=5,
            namespace="docs",
            strategy="hybrid",
            max_staleness_hours=72,
            output_property="augment_result",
        )

    Property ``augment_result`` = dict() форма для downstream-process'ов
    (см. :meth:`AugmentResult.to_dict`).
    """

    def __init__(
        self,
        query_field: str = "question",
        system_prompt: str = "",
        top_k: int = 5,
        namespace: str | None = None,
        strategy: str = "dense",
        max_staleness_hours: float | None = None,
        output_property: str = "augment_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        if strategy not in _RAG_STRATEGIES:
            raise ValueError(
                f"unknown rag strategy '{strategy}'; expected one of {_RAG_STRATEGIES}"
            )
        self._query_field = query_field
        self._system_prompt = system_prompt
        self._top_k = top_k
        self._namespace = namespace
        self._strategy = strategy
        self._max_staleness = max_staleness_hours
        self._output_property = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if isinstance(body, dict):
            query = body.get(self._query_field, "")
        else:
            query = str(body)
        if not query:
            exchange.set_property(self._output_property, None)
            return
        from src.backend.services.ai.rag_service import get_rag_service

        # S11 K4 W3: adaptive — селектор выбирает реальную стратегию
        # на основе query-features + feature_flag.
        effective_strategy = self._strategy
        if effective_strategy == "adaptive":
            from src.backend.core.config.features import feature_flags

            if feature_flags.adaptive_rag_strategy:
                from src.backend.services.ai.rag.strategy_selector import (
                    AdaptiveStrategySelector,
                )

                selector = AdaptiveStrategySelector()
                decision = await selector.select(query)
                effective_strategy = decision.strategy
                exchange.set_property("rag_strategy_overhead_ms", decision.elapsed_ms)
            else:
                effective_strategy = "dense"

        rag = get_rag_service()
        result = await rag.augment(
            query=query,
            system_prompt=self._system_prompt,
            top_k=self._top_k,
            namespace=self._namespace,
            max_staleness_hours=self._max_staleness,
        )
        payload = result.to_dict()
        # Прокидываем strategy в downstream:
        # — exchange property для branch-logic,
        # — поле augment_result для каждого консьюмера, читающего dict.
        payload["strategy"] = effective_strategy
        exchange.set_property("rag_strategy", effective_strategy)
        exchange.set_property(self._output_property, payload)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._query_field != "question":
            spec["query_field"] = self._query_field
        if self._top_k != 5:
            spec["top_k"] = self._top_k
        if self._namespace is not None:
            spec["namespace"] = self._namespace
        if self._strategy != "dense":
            spec["strategy"] = self._strategy
        if self._max_staleness is not None:
            spec["max_staleness_hours"] = self._max_staleness
        if self._system_prompt:
            spec["system_prompt"] = self._system_prompt
        if self._output_property != "augment_result":
            spec["output_property"] = self._output_property
        return {"rag_query": spec}
