"""Auto-generated from ai_processors.py — single processor files."""

from __future__ import annotations

from typing import Any, Callable

import orjson

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor


class LLMCallProcessor(BaseProcessor):
    """Вызывает LLM с retry, rate-limit detection и cost tracking.

    Сохраняет в properties:
    - llm.provider — фактически использованный провайдер
    - llm.model — модель
    - llm.tokens_used — количество токенов (если LLM вернул usage)
    - llm.cost_usd — оценка стоимости (если есть таблица цен в config)

    Args:
        max_retries: Количество повторов при transient ошибках (default 2).
        retry_delay: Базовая задержка между retry (сек).
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        prompt_property: str = "_composed_prompt",
        max_retries: int = 2,
        retry_delay: float = 1.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._provider = provider
        self._model = model
        self._prompt_property = prompt_property
        self._max_retries = max_retries
        self._retry_delay = retry_delay

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import logging

        from src.backend.infrastructure.resilience.retry import make_async_retry

        prompt = exchange.properties.get(self._prompt_property)
        if prompt is None:
            prompt = (
                exchange.in_message.body
                if isinstance(exchange.in_message.body, str)
                else str(exchange.in_message.body)
            )

        # S30 w4: сохраняем prompt для NeMo output guardrails
        exchange.set_property("llm.original_prompt", prompt)

        _log = logging.getLogger("dsl.ai")

        try:
            from src.backend.services.ai.ai_agent import get_ai_agent_service
        except ImportError as exc:
            exchange.fail(f"AI agent service unavailable: {exc}")
            return

        agent = get_ai_agent_service()

        # K3 W1: замена custom retry-loop на tenacity через make_async_retry.
        # Rate-limit (RuntimeError с "rate"/"429"/"quota") — non-retryable,
        # обрабатывается отдельно до вызова retry-обёртки.
        _retryable = (TimeoutError, ConnectionError)

        @make_async_retry(
            max_attempts=self._max_retries + 1,
            initial_backoff=self._retry_delay,
            multiplier=2.0,
            on=_retryable,
        )
        async def _chat_with_retry() -> Any:
            """Выполняет один LLM-запрос; tenacity перехватывает transient ошибки."""
            try:
                return await agent.chat(
                    messages=[{"role": "user", "content": prompt}],
                    provider=self._provider,
                    model=self._model or "default",
                )
            except RuntimeError as exc:
                msg = str(exc).lower()
                if "rate" in msg or "429" in msg or "quota" in msg:
                    # Rate-limit — non-retryable, пробрасываем как есть.
                    raise
                # Остальные RuntimeError считаем transient — оборачиваем
                # в ConnectionError, чтобы tenacity их поймал.
                raise ConnectionError(str(exc)) from exc

        try:
            result = await _chat_with_retry()
        except RuntimeError as exc:
            # rate-limit или другие non-retryable RuntimeError
            exchange.fail(f"LLM rate limit: {exc}")
            return
        except (TimeoutError, ConnectionError) as exc:
            exchange.fail(
                f"LLM call failed after {self._max_retries + 1} attempts: {exc}"
            )
            return

        if isinstance(result, dict):
            usage = result.get("usage") or {}
            tokens = int(usage.get("total_tokens", 0)) if usage else 0
            if tokens:
                exchange.set_property("llm.tokens_used", tokens)
                exchange.set_property("llm.cost_usd", round(tokens * 0.00002, 6))
            if "model" in result:
                exchange.set_property("llm.model", result["model"])

        exchange.set_property("llm.provider", self._provider or "fallback")
        exchange.in_message.set_body(result)

        _log.info(
            "llm_call_ok",
            extra={
                "provider": self._provider,
                "model": self._model,
                "tokens": exchange.properties.get("llm.tokens_used", 0),
            },
        )

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._provider is not None:
            spec["provider"] = self._provider
        if self._model is not None:
            spec["model"] = self._model
        return {"call_llm": spec}
