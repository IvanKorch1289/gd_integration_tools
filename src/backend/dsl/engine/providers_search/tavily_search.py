"""TavilySearchProcessor — dedicated DSL processor для Tavily (S171 M19.2).

Per Tavily API docs:
- search_depth: "basic" | "advanced"
- max_results: 1-20
- include_answer: bool
- include_raw_content: bool

Ponytail (D250, D251): thin wrapper над capability-checked facade.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_logger = get_logger("dsl.search.tavily")

__all__ = ("TavilySearchProcessor",)


class TavilySearchProcessor(BaseProcessor):
    """DSL processor для Tavily API.

    Args:
        query: Поисковый запрос.
        search_depth: "basic" | "advanced" (default "basic").
        max_results: Максимум результатов 1-20 (default 5).
        include_answer: Включить "answer" в результат (default True).
        include_raw_content: Включить raw content (default False).
        to: Куда положить результат (default "body.tavily_result").
    """

    required_capability: str | None = "web_search.tavily.invoke"
    audit_event: str | None = "web_search.tavily.invoked"

    VALID_DEPTHS = ("basic", "advanced")

    def __init__(
        self,
        *,
        query: str,
        search_depth: str = "basic",
        max_results: int = 5,
        include_answer: bool = True,
        include_raw_content: bool = False,
        to: str = "body.tavily_result",
        name: str | None = None,
    ) -> None:
        if search_depth not in self.VALID_DEPTHS:
            raise ValueError(
                f"search_depth должен быть одним из {self.VALID_DEPTHS}, "
                f"получено {search_depth!r}"
            )
        if not 1 <= max_results <= 20:
            raise ValueError(
                f"max_results должен быть 1-20, получено {max_results}"
            )
        super().__init__(name=name or "tavily_search")
        self.query = query
        self.search_depth = search_depth
        self.max_results = max_results
        self.include_answer = include_answer
        self.include_raw_content = include_raw_content
        self.target = to

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        """Выполняет web-поиск через Tavily API и пишет результаты в target."""
        # Lazy import — capability-checked facade (D102)
        from src.backend.core.integrations.web_search import get_tavily_provider_class
        ProviderClass = get_tavily_provider_class()
        provider = ProviderClass()

        resolved_query = self.query
        head, _, rest = self.query.partition(".")
        if head == "body" and rest:
            cursor: Any = exchange.in_message.body
            for part in rest.split("."):
                cursor = cursor.get(part) if isinstance(cursor, dict) else None
            if cursor is not None:
                resolved_query = str(cursor)

        provider = get_tavily_provider()
        response = await provider.search(
            query=resolved_query,
            search_depth=self.search_depth,
            max_results=self.max_results,
            include_answer=self.include_answer,
            include_raw_content=self.include_raw_content,
        )
        _logger.info(
            "tavily.search query=%s depth=%s results=%d",
            resolved_query, self.search_depth,
            len(response.get("results", [])),
        )
        self.set_result(exchange, self.target, response)
