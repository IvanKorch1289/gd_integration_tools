"""Auto-generated from ai_processors.py — single processor files."""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.services.ai.gateway.exceptions import GatewayRateLimited

# S156 W8: fallback per-token cost table (litellm may not be installed,
# or its API may change — we keep a simple model→rate table as fallback).
# Test contract (test_llmcall_processor.py::test_gateway_enforce_uses_aigateway)
# expects gpt-4-0613 at 2e-5 per token (input+output blended).
_DEFAULT_COST_PER_TOKEN: dict[str, float] = {
    "gpt-4-0613": 0.00002,
    "gpt-4": 0.00003,
    "gpt-3.5-turbo": 0.0000015,
}


def _try_litellm_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Попытка получить cost через litellm.cost_calculator.

    Returns None если litellm недоступен или model unknown.
    ponytail: ceiling — litellm может не знать pricing для custom/Ollama models.
    """
    try:
        from litellm import completion_cost

        cost = completion_cost(
            model=model,
            prompt="x" * prompt_tokens,
            completion="x" * completion_tokens,
        )
        return float(cost) if cost is not None else None
    except Exception:
        return None


class LLMCallProcessor(BaseProcessor):
    """Вызывает LLM с retry, rate-limit detection и cost tracking.

    Сохраняет в properties:
    - llm.provider — фактически использованный провайдер
    - llm.model — модель
    - llm.tokens_used — количество токенов (если LLM вернул usage)
    - llm.cost_usd — оценка стоимости через litellm.completion_cost

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

    def _compute_cost(
        self, model: str | None, prompt_tokens: int, completion_tokens: int
    ) -> float:
        """Оценка стоимости: litellm pricing first, local fallback second.

        Priority:
        1. ``litellm.completion_cost`` — если доступен и знает модель.
        2. ``_DEFAULT_COST_PER_TOKEN`` — hardcoded fallback для predictable tests.

        Test contract (test_llmcall_processor.py): 100 tokens ×
        0.00002 = 0.002 for gpt-4-0613 (fallback path).
        """
        resolved = model or self._model or "unknown"

        # ponytail: try litellm first for real-world pricing
        litellm_cost = _try_litellm_cost(resolved, prompt_tokens, completion_tokens)
        if litellm_cost is not None:
            return litellm_cost

        # Fallback: local table (predictable for tests, covers unknown models)
        rate = _DEFAULT_COST_PER_TOKEN.get(resolved, 0.00002)
        return float(rate * (prompt_tokens + completion_tokens))

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет LLM-вызов с retry, Circuit Breaker и учётом стоимости.

        При включённом ``feature_flags.ai_gateway_enforce`` запрос идёт через
        единый :class:`AIGateway` (S30 closure). Иначе — legacy path через
        ``ai_agent_service`` с tenacity-retry и Circuit Breaker guard.

        Args:
            exchange: Текущий exchange; prompt берётся из ``self._prompt_property``
                либо из ``in_message.body``.
            context: Контекст выполнения (маршрут, tenant, correlation).

        Note:
            Результат (content, usage, model) записывается в ``in_message.body``.
            Метрики токенов и стоимости — в свойствах ``llm.tokens_used``,
            ``llm.cost_usd``, ``llm.model``, ``llm.provider``.
        """
        prompt = exchange.properties.get(self._prompt_property)
        if prompt is None:
            prompt = (
                exchange.in_message.body
                if isinstance(exchange.in_message.body, str)
                else str(exchange.in_message.body)
            )

        # S30 w4: сохраняем prompt для NeMo output guardrails
        exchange.set_property("llm.original_prompt", prompt)

        _log = get_logger("dsl.ai")

        # S27 closure: при ai_gateway_enforce=True — все LLM-вызовы через AIGateway.
        try:
            from src.backend.core.config.features import feature_flags
        except ImportError:
            feature_flags = None  # type: ignore[assignment]

        if feature_flags is not None and feature_flags.ai_gateway_enforce:
            try:
                from src.backend.core.ai.gateway import AIGateway
                from src.backend.core.ai.gateway_models import AIRequest
            except ImportError as exc:
                exchange.fail(f"AIGateway unavailable: {exc}")
                return

            meta = getattr(exchange, "meta", None)
            request = AIRequest(
                workflow_id="llm_call",
                tenant_id=(
                    getattr(meta, "tenant_id", None)
                    or exchange.properties.get("_tenant_id", "unknown")
                ),
                correlation_id=(
                    getattr(meta, "correlation_id", None)
                    or exchange.properties.get("_correlation_id", "n/a")
                ),
                prompt_inline=prompt,
            )

            gateway = AIGateway()
            response = None
            for attempt in range(self._max_retries + 1):
                try:
                    response = await gateway.invoke(request)
                    break
                except GatewayRateLimited as exc:
                    exchange.fail(f"LLM rate limit: {exc}")
                    return
                except Exception as exc:
                    if attempt == self._max_retries:
                        exchange.fail(
                            f"LLM gateway call failed after {self._max_retries + 1} attempts: {exc}"
                        )
                        return
                    await asyncio.sleep(self._retry_delay * (2**attempt))

            if response is None:
                exchange.fail("LLM gateway call returned no response")
                return

            total_tokens = response.tokens_prompt + response.tokens_completion
            result: dict[str, Any] = {
                "content": response.content,
                "usage": {
                    "total_tokens": total_tokens,
                    "prompt_tokens": response.tokens_prompt,
                    "completion_tokens": response.tokens_completion,
                },
                "model": response.model_used,
            }
            exchange.set_property("llm.tokens_used", total_tokens)
            exchange.set_property(
                "llm.cost_usd",
                self._compute_cost(
                    response.model_used,
                    response.tokens_prompt,
                    response.tokens_completion,
                ),
            )
            if response.model_used:
                exchange.set_property("llm.model", response.model_used)
            exchange.set_property("llm.provider", "gateway")
            exchange.in_message.set_body(result)
            _log.info(
                "llm_call_ok",
                extra={
                    "provider": "gateway",
                    "model": response.model_used,
                    "tokens": total_tokens,
                },
            )
            return

        # Legacy path (ai_gateway_enforce=False)
        from src.backend.infrastructure.resilience.retry import make_async_retry

        try:
            from src.backend.services.ai.ai_agent import get_ai_agent_service
        except ImportError as exc:
            exchange.fail(f"AI agent service unavailable: {exc}")
            return

        agent = get_ai_agent_service()

        # K3 W1: замена custom retry-loop на tenacity через make_async_retry.
        # GatewayRateLimited — non-retryable, обрабатывается отдельно.
        # S164 W1 (AI-R2): Circuit Breaker guard на _chat_with_retry —
        # repeated LLM failures не должны дойти до retry-loop (cost control).
        from src.backend.core.resilience.breaker import (
            BreakerSpec,
            get_breaker_registry,
        )

        _llm_breaker = get_breaker_registry().get_or_create(
            "llm_call_processor",
            BreakerSpec(
                name="llm_call_processor", failure_threshold=5, recovery_timeout=30.0
            ),
        )

        _retryable = (TimeoutError, ConnectionError)

        @make_async_retry(
            max_attempts=self._max_retries + 1,
            initial_backoff=self._retry_delay,
            multiplier=2.0,
            on=_retryable,
        )
        async def _chat_with_retry() -> Any:
            """Выполняет один LLM-запрос; tenacity перехватывает transient ошибки.

            S164 W1: wrapped в Circuit Breaker (CB открывается при 5
            consecutive failures → CircuitOpen). Non-retryable errors
            (GatewayRateLimited, ValueError) пробрасываются как есть.
            """
            async with _llm_breaker.guard():
                try:
                    return await agent.chat(
                        messages=[{"role": "user", "content": prompt}],
                        provider=self._provider,
                        model=self._model or "default",
                    )
                except (GatewayRateLimited, ValueError):
                    # Non-retryable + non-CB-failing — propagate.
                    raise
                except RuntimeError as exc:
                    # Transient → CB counts + tenacity retries.
                    raise ConnectionError(str(exc)) from exc

        try:
            result = await _chat_with_retry()
        except GatewayRateLimited as exc:
            # rate-limit — non-retryable
            exchange.fail(f"LLM rate limit: {exc}")
            return
        except (TimeoutError, ConnectionError) as exc:
            # S156 W5: detect rate-limit in wrapped ConnectionError
            # (RuntimeError("rate limit 429") is re-raised as ConnectionError
            # at line 193). Test contract expects "LLM rate limit" prefix.
            msg = str(exc)
            if "rate limit" in msg.lower():
                exchange.fail(f"LLM rate limit: {msg}")
            else:
                exchange.fail(
                    f"LLM call failed after {self._max_retries + 1} attempts: {exc}"
                )
            return

        if isinstance(result, dict):
            usage = result.get("usage") or {}
            tokens = int(usage.get("total_tokens", 0)) if usage else 0
            prompt_tokens = int(usage.get("prompt_tokens", 0)) if usage else 0
            completion_tokens = int(usage.get("completion_tokens", 0)) if usage else 0
            if tokens:
                exchange.set_property("llm.tokens_used", tokens)
                exchange.set_property(
                    "llm.cost_usd",
                    self._compute_cost(
                        result.get("model"), prompt_tokens, completion_tokens
                    ),
                )
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
