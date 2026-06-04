"""K3 S5 W9 — DSL-процессор ``web_search``: поиск через провайдер.

Wave ``[wave:s5/k3-w9-web-search-builder]``.

Использует существующий :class:`WebSearchService` из
``src.backend.infrastructure.clients.external.search_providers`` (Tavily /
Perplexity / SearXNG fallback chain).

Контракт DSL::

    .web_search(
        engine="tavily",
        query_source="body.query",
        max_results=10,
        to="body.search_results",
    )

YAML::

    - web_search:
        engine: tavily
        query_source: body.query
        max_results: 10
        to: body.search_results

Feature flag: ``feature_flags.web_search_enabled`` (default-OFF).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("WebSearchProcessor",)


_ALLOWED_ENGINES = frozenset({"tavily", "perplexity", "searxng", "auto"})


@processor(
    "web_search",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "engine": {"type": "string", "enum": sorted(_ALLOWED_ENGINES)},
            "query": {"type": ["string", "null"]},
            "query_source": {"type": ["string", "null"]},
            "max_results": {"type": "integer"},
            "to": {"type": "string"},
            "deep_research": {"type": "boolean"},
        },
    },
    capabilities=("net.outbound.search:external",),
    meta={"tier": 1, "category": "ai"},
    tags=("web-search", "ai", "rag"),
)
class WebSearchProcessor(BaseProcessor):
    """Web-search через WebSearchService.

    Args:
        engine: ``tavily`` / ``perplexity`` / ``searxng`` / ``auto`` (fallback).
        query: Прямой query (если задан).
        query_source: ``body.<field>`` или ``properties.<name>`` — где взять query.
        max_results: Максимум результатов.
        to: Куда положить результат.
        deep_research: Использовать deep_research() вместо search().
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL

    def __init__(
        self,
        engine: str = "auto",
        *,
        query: str | None = None,
        query_source: str | None = None,
        max_results: int = 10,
        to: str = "body.search_results",
        deep_research: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"web_search:{engine}")
        if engine not in _ALLOWED_ENGINES:
            raise ValueError(
                f"web_search: engine must be one of {sorted(_ALLOWED_ENGINES)}, "
                f"got {engine!r}"
            )
        if max_results < 1:
            raise ValueError("web_search: max_results must be >= 1")
        self._engine = engine
        self._query = query
        self._query_source = query_source
        self._max_results = max_results
        self._target = to
        self._deep_research = deep_research

    def _resolve_query(self, exchange: Exchange[Any]) -> str | None:
        if self._query:
            return self._query
        if not self._query_source:
            body = exchange.in_message.body
            if isinstance(body, str):
                return body
            return None
        body = exchange.in_message.body
        if self._query_source.startswith("body."):
            field = self._query_source[len("body.") :]
            value = body.get(field) if isinstance(body, dict) else None
        elif self._query_source.startswith("properties."):
            field = self._query_source[len("properties.") :]
            value = exchange.properties.get(field)
        else:
            value = None
        return str(value) if value is not None else None

    def _apply_target(self, exchange: Exchange[Any], value: Any) -> None:
        if self._target.startswith("body."):
            field = self._target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body
            body[field] = value
            return
        if self._target.startswith("properties."):
            field = self._target[len("properties.") :]
            exchange.set_property(field, value)
            return
        exchange.set_property(self._target, value)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.web_search_enabled:
                exchange.set_property("web_search_status", "skipped")
                return
        except Exception as _:
            pass

        query = self._resolve_query(exchange)
        if not query:
            exchange.fail("web_search: query not provided / not found in source")
            return

        try:
            from src.backend.infrastructure.clients.external.search_providers import (
                get_web_search_service,
            )

            service = get_web_search_service()
            provider = None if self._engine == "auto" else self._engine
            if self._deep_research:
                result: Any = await service.deep_research(query, provider=provider)
            else:
                result = await service.query(
                    query, max_results=self._max_results, provider=provider
                )
        except Exception as exc:
            exchange.fail(f"web_search error: {exc}")
            return

        self._apply_target(exchange, result)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"engine": self._engine}
        if self._query:
            spec["query"] = self._query
        if self._query_source:
            spec["query_source"] = self._query_source
        if self._max_results != 10:
            spec["max_results"] = self._max_results
        if self._target != "body.search_results":
            spec["to"] = self._target
        if self._deep_research:
            spec["deep_research"] = True
        return {"web_search": spec}
