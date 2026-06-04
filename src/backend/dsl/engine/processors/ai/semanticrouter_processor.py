"""Auto-generated from ai_processors.py — single processor files."""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor


class SemanticRouterProcessor(BaseProcessor):
    """Маршрутизация по семантическому сходству — RAG-based intent routing.

    Принимает text input, ищет ближайший intent через RAG vector search,
    делегирует выполнение в соответствующий route_id.

    Usage::

        .semantic_route(intents={
            "order_status": "route.orders",
            "complaint": "route.support",
            "billing": "route.billing",
        }, default_route="route.general")
    """

    def __init__(
        self,
        intents: dict[str, str],
        *,
        default_route: str | None = None,
        query_field: str = "question",
        threshold: float = 0.5,
        namespace: str = "intents",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "semantic_router")
        self._intents = intents
        self._default_route = default_route
        self._query_field = query_field
        self._threshold = threshold
        self._namespace = namespace

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        query = body.get(self._query_field, "") if isinstance(body, dict) else str(body)

        if not query:
            if self._default_route:
                await self._route_to(self._default_route, exchange, context)
                return
            exchange.fail("SemanticRouter: empty query and no default_route")
            return

        try:
            from src.backend.services.ai.rag_service import get_rag_service

            rag = get_rag_service()
            results = await rag.search(query=query, top_k=1, namespace=self._namespace)
        except (ImportError, ConnectionError, TimeoutError, RuntimeError) as exc:
            if self._default_route:
                exchange.set_property("semantic_route_fallback", str(exc))
                await self._route_to(self._default_route, exchange, context)
                return
            exchange.fail(f"SemanticRouter RAG search failed: {exc}")
            return

        target_intent: str | None = None
        score = 0.0
        if results:
            top = results[0]
            score = top.get("score", 0.0) if isinstance(top, dict) else 0.0
            intent_name = (
                top.get("intent") or top.get("metadata", {}).get("intent")
                if isinstance(top, dict)
                else None
            )
            if intent_name and score >= self._threshold:
                target_intent = intent_name

        target_route = self._intents.get(target_intent or "", self._default_route)
        if not target_route:
            exchange.fail(
                f"SemanticRouter: no matching intent for query (score={score:.3f})"
            )
            return

        exchange.set_property("semantic_route_intent", target_intent)
        exchange.set_property("semantic_route_score", score)
        await self._route_to(target_route, exchange, context)

    @staticmethod
    async def _route_to(
        route_id: str, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        from src.backend.dsl.engine.processors.base import SubPipelineExecutor

        result, error = await SubPipelineExecutor.execute_route(
            route_id,
            exchange.in_message.body,
            dict(exchange.in_message.headers),
            context,
        )
        if error:
            exchange.fail(f"Semantic route {route_id} failed: {error}")
            return
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
