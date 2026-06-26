"""PerplexitySearchProcessor — dedicated DSL processor (S171 M19.2).

Per Perplexity API docs:
- model: "sonar" | "sonar-pro" | "sonar-reasoning"
- max_tokens: int
- temperature: 0-1

Ponytail (D250, D251): thin wrapper над capability-checked facade.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_logger = get_logger("dsl.search.perplexity")

__all__ = ("PerplexitySearchProcessor",)


class PerplexitySearchProcessor(BaseProcessor):
    """DSL processor для Perplexity API.

    Args:
        query: Поисковый запрос.
        model: "sonar" | "sonar-pro" (default "sonar-pro" — лучший).
        max_tokens: Максимум токенов в ответе (default 1000).
        temperature: 0.0-1.0 (default 0.2 — факты).
        to: Куда положить результат (default "body.perplexity_result").
    """

    required_capability: str | None = "web_search.perplexity.invoke"
    audit_event: str | None = "web_search.perplexity.invoked"

    VALID_MODELS = ("sonar", "sonar-pro", "sonar-reasoning")

    def __init__(
        self,
        *,
        query: str,
        model: str = "sonar-pro",
        max_tokens: int = 1000,
        temperature: float = 0.2,
        to: str = "body.perplexity_result",
        name: str | None = None,
    ) -> None:
        if model not in self.VALID_MODELS:
            raise ValueError(
                f"model должен быть одним из {self.VALID_MODELS}, "
                f"получено {model!r}"
            )
        if not 0.0 <= temperature <= 1.0:
            raise ValueError(
                f"temperature должен быть 0.0-1.0, получено {temperature}"
            )
        super().__init__(name=name or "perplexity_search")
        self.query = query
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.target = to

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        # Lazy import — capability-checked facade (D102)
        from src.backend.core.integrations.web_search import get_perplexity_provider_class
        ProviderClass = get_perplexity_provider_class()
        provider = ProviderClass()

        resolved_query = self.query
        head, _, rest = self.query.partition(".")
        if head == "body" and rest:
            cursor: Any = exchange.in_message.body
            for part in rest.split("."):
                cursor = cursor.get(part) if isinstance(cursor, dict) else None
            if cursor is not None:
                resolved_query = str(cursor)

        provider = get_perplexity_provider()
        response = await provider.search(
            query=resolved_query,
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        _logger.info(
            "perplexity.search query=%s model=%s tokens=%d",
            resolved_query, self.model, self.max_tokens,
        )
        self.set_result(exchange, self.target, response)
