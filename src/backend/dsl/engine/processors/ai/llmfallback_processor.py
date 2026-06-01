"""Auto-generated from ai_processors.py — single processor files."""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor


class LLMFallbackProcessor(BaseProcessor):
    """Пробует несколько LLM-провайдеров по цепочке.

    При недоступности primary провайдера автоматически
    переключается на следующий. Полезно для production-надёжности.

    Usage::

        .call_llm_with_fallback(providers=["perplexity", "huggingface", "open_webui"])
    """

    def __init__(
        self,
        providers: list[str],
        *,
        model: str = "default",
        prompt_property: str = "_composed_prompt",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"llm_fallback({len(providers)})")
        self._providers = providers
        self._model = model
        self._prompt_property = prompt_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        prompt = exchange.properties.get(self._prompt_property)
        if prompt is None:
            prompt = (
                exchange.in_message.body
                if isinstance(exchange.in_message.body, str)
                else str(exchange.in_message.body)
            )

        from src.backend.services.ai.ai_agent import get_ai_agent_service

        agent = get_ai_agent_service()

        last_error: str | None = None
        for provider in self._providers:
            try:
                result = await agent.chat(
                    messages=[{"role": "user", "content": prompt}],
                    provider=provider,
                    model=self._model,
                )
                exchange.in_message.set_body(result)
                exchange.set_property("llm_provider_used", provider)
                return
            except Exception as exc:
                last_error = f"{provider}: {exc}"

        exchange.fail(f"All LLM providers failed. Last error: {last_error}")
