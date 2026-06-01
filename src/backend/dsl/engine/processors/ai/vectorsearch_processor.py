"""Auto-generated from ai_processors.py — single processor files."""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor


class VectorSearchProcessor(BaseProcessor):
    """Ищет в RAG vector store, результаты в exchange properties."""

    def __init__(
        self,
        query_field: str = "question",
        top_k: int = 5,
        namespace: str | None = None,
        output_property: str = "vector_results",
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._query_field = query_field
        self._top_k = top_k
        self._namespace = namespace
        self._output_property = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if isinstance(body, dict):
            query = body.get(self._query_field, "")
        else:
            query = str(body)
        if not query:
            exchange.set_property(self._output_property, [])
            return
        from src.backend.services.ai.rag_service import get_rag_service

        rag = get_rag_service()
        results = await rag.search(
            query=query, top_k=self._top_k, namespace=self._namespace
        )
        exchange.set_property(self._output_property, results)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._query_field != "question":
            spec["query_field"] = self._query_field
        if self._top_k != 5:
            spec["top_k"] = self._top_k
        if self._namespace is not None:
            spec["namespace"] = self._namespace
        return {"rag_search": spec}


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
