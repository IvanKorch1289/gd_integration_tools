"""DSL processor ``rag_search`` (Sprint 170 S170 — agent layer).

Thin wrapper над :class:`src.backend.services.ai.hybrid_rag.HybridRAGSearch.search`.
Ponytail: facade-isolated, BM25+vector+reranker hybrid.
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("RAGSearchProcessor",)
_logger = get_logger(__name__)


class RAGSearchProcessor(BaseProcessor):
    """Hybrid RAG search через DSL.

    Args:
        query: Поисковый запрос.
        collection: Имя коллекции (default ``"default"``).
        to: Куда записать список docs (``body.field`` или property).
        top_k: Количество результатов (default 5).
    """

    def __init__(
        self,
        *,
        query: str,
        to: str = "body.docs",
        top_k: int = 5,
        namespace: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"rag_search:{query[:30]}")
        self.query = query
        self.target = to
        self.top_k = top_k
        self.namespace = namespace

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.services.ai.hybrid_rag import HybridRAGSearch
        search = HybridRAGSearch()
        docs = await search.search(
            self.query, top_k=self.top_k, namespace=self.namespace
        )
        self.set_result(exchange, self.target, docs)
