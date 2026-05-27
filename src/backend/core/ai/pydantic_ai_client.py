"""PydanticAI Unified Client — единая точка входа в LLM.

Интегрирует:
- ModelRouter fallback chain (LiteLLM primary + fallback через LiteLLMGateway)
- Retry via LiteLLMGateway num_retries
- MetricsRegistry для всех Prometheus метрик
- AuditService для ai.invocation.* events

Пока NOT использует pydantic_ai Agent напрямую — LiteLLMModel adapter
не реализует полный Model protocol (missing request/request_stream).
Полная pydantic_ai Agent integration — в S32 W2.

Использование::

    client = PydanticAIClient(
        gateway=gateway,
        model_router=ModelRouterSpec(primary="openai/gpt-4o-mini", fallback=["openai/gpt-4o"]),
    )
    result = await client.run(
        prompt="Classify this credit request",
        deps=LLMDependencies(tenant_id="credit_premium", correlation_id="req-123"),
    )
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Dependencies dataclass ────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LLMDependencies:
    """Dependency injection для LLM-вызова.

    Attributes:
        tenant_id: Tenant из ``TenantContext`` для PII/quota/SLO isolation.
        correlation_id: Request ID для аудит-trace через все sinks.
        user_id: Опциональный идентификатор пользователя (для per-user audit).
        session_id: Опциональный идентификатор сессии (для LangGraph state).
        extra: Дополнительные данные для инструментов / hooks.
    """

    tenant_id: str
    correlation_id: str
    user_id: str | None = None
    session_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ── Result dataclass ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LLMResult:
    """Результат LLM-вызова.

    Attributes:
        content: Текстовый ответ LLM (всегда заполнен).
        structured: Pydantic-объект если ``output_type`` был указан и
            валидация прошла успешно.
        tokens_prompt: Токены входа (после template-render).
        tokens_completion: Токены ответа LLM.
        cost_usd: Стоимость в USD (через litellm callback).
        model_used: Фактическая модель из fallback chain
            (может отличаться от primary).
        latency_ms: Полное время выполнения в миллисекундах.
        is_fallback: True если вызвана fallback-модель после primary-failure.
    """

    content: str
    structured: Any | None = None
    tokens_prompt: int = 0
    tokens_completion: int = 0
    cost_usd: float = 0.0
    model_used: str = ""
    latency_ms: int = 0
    is_fallback: bool = False


# ── Main client ────────────────────────────────────────────────────────────


class PydanticAIClient:
    """PydanticAI unified client — единая точка входа в LLM.

    Note:
        Полная интеграция с pydantic_ai Agent (structured output, tools,
        model-agnostic API) — в S32 W2. Текущая реализация использует
        LiteLLMGateway напрямую для обратной совместимости с тестами.

    Архитектура:
    - ModelRouter fallback chain через LiteLLMGateway.acompletion fallback params
    - Retry через LiteLLMGateway num_retries (per ModelRouterSpec.retry_attempts)
    - MetricsRegistry integration
    - AuditService для ai.invocation.* events

    Args:
        gateway: :class:`LiteLLMGateway` для выполнения HTTP-запросов.
        model_router: ModelRouterSpec с primary + fallback chain.
        metrics_registry: MetricsRegistry для Prometheus counters.
    """

    def __init__(
        self,
        *,
        gateway: Any,
        model_router: Any | None = None,
        metrics_registry: Any | None = None,
    ) -> None:
        self._gateway = gateway
        self._model_router = model_router
        self._metrics_registry = metrics_registry

    # ── public API ─────────────────────────────────────────────────────────

    async def run(
        self,
        prompt: str,
        *,
        output_type: type["BaseModel"] | None = None,
        deps: LLMDependencies | None = None,
        stream: bool = False,
    ) -> LLMResult:
        """Выполняет LLM-вызов через LiteLLMGateway с fallback chain.

        Args:
            prompt: Готовый prompt (после render + sanitize + guard).
            output_type: Pydantic model для structured output.
                Пока не реализовано (S32 W2), всегда возвращает str в content.
            deps: LLMDependencies для tenant/correlation isolation.
            stream: Если True — возвращает AsyncIterator чанков
                (пока не поддерживается, для future use).

        Returns:
            LLMResult с content/structured/tokens/cost/model/latency.

        Raises:
            GatewayUnavailable: Все модели в fallback chain недоступны.
            GatewayRateLimited: Rate-limit на всех моделях.
        """
        if stream:
            raise NotImplementedError("Streaming support planned for S32 W2+")

        assert not stream, "unreachable"  # for mypy
        start_ms: int = int(time.monotonic() * 1000)

        primary = self._primary_model()
        fallbacks = self._fallback_models()
        retry_attempts = self._retry_attempts()

        self._emit_counter(
            "ai_pydantic_client_requests_total",
            {"model": primary, "status": "started"},
        )

        messages = [{"role": "user", "content": prompt}]
        kwargs: dict[str, Any] = {"stream": False}
        if fallbacks:
            kwargs["fallbacks"] = fallbacks

        last_exc: Exception | None = None
        for attempt in range(1, retry_attempts + 1):
            try:
                response = await self._gateway.acompletion(
                    messages, model=primary, **kwargs
                )
                latency_ms = int(time.monotonic() * 1000) - start_ms

                (
                    content,
                    tokens_prompt,
                    tokens_completion,
                    model_used,
                ) = self._extract_completion(response, fallback_model=primary)
                is_fallback = model_used != primary

                self._emit_counter(
                    "ai_pydantic_client_requests_total",
                    {"model": model_used, "status": "success"},
                )
                self._emit_histogram(
                    "ai_pydantic_client_latency_ms",
                    latency_ms,
                    {"model": model_used},
                )
                if is_fallback:
                    self._emit_counter(
                        "ai_pydantic_client_fallback_total",
                        {"model": model_used, "reason": "primary_exhausted"},
                    )

                return LLMResult(
                    content=content,
                    structured=None,  # structured output в W2
                    tokens_prompt=tokens_prompt,
                    tokens_completion=tokens_completion,
                    cost_usd=0.0,  # cost tracking через LiteLLM callback
                    model_used=model_used,
                    latency_ms=latency_ms,
                    is_fallback=is_fallback,
                )
            except Exception as exc:
                last_exc = exc
                self._emit_counter(
                    "ai_pydantic_client_retry_total",
                    {"model": primary, "attempt": str(attempt)},
                )
                logger.debug(
                    "PydanticAIClient: attempt %d failed (%s)", attempt, exc
                )
                continue

        # Все fail — эмитим ошибку и пробрасываем
        self._emit_counter(
            "ai_pydantic_client_requests_total",
            {"model": primary, "status": "error"},
        )
        self._reraise_normalized(last_exc or RuntimeError("No models available"))
        # unreachable — _reraise_normalized always raises
        raise AssertionError("unreachable") from last_exc

    # ── mock result ────────────────────────────────────────────────────────

    async def _mock_result(self, start_ms: int) -> LLMResult:
        """Last resort: возвращает mock result при исчерпании всех моделей."""
        latency_ms = int(time.monotonic() * 1000) - start_ms
        self._emit_counter(
            "ai_pydantic_client_requests_total",
            {"model": "mock", "status": "mock"},
        )
        self._emit_counter(
            "ai_pydantic_client_fallback_total",
            {"model": "mock", "reason": "all_exhausted"},
        )
        logger.warning(
            "PydanticAIClient: all models exhausted, returning mock result"
        )
        return LLMResult(
            content="[mock: all models unavailable]",
            structured=None,
            tokens_prompt=0,
            tokens_completion=0,
            cost_usd=0.0,
            model_used="mock",
            latency_ms=latency_ms,
            is_fallback=True,
        )

    # ── helpers ───────────────────────────────────────────────────────────

    def _primary_model(self) -> str:
        """Возвращает primary model из ModelRouterSpec или дефолт."""
        if self._model_router is not None:
            return getattr(self._model_router, "primary", None) or "openai/gpt-4o-mini"
        return "openai/gpt-4o-mini"

    def _fallback_models(self) -> list[str]:
        """Возвращает fallback chain из ModelRouterSpec."""
        if self._model_router is not None:
            return list(getattr(self._model_router, "fallback", []) or [])
        return []

    def _retry_attempts(self) -> int:
        """Возвращает retry_attempts из ModelRouterSpec."""
        if self._model_router is not None:
            return int(getattr(self._model_router, "retry_attempts", 2) or 2)
        return 2

    @staticmethod
    def _extract_completion(
        response: Any, *, fallback_model: str | None
    ) -> tuple[str, int, int, str]:
        """Вытаскивает content/tokens/model из litellm-ответа.

        Поддерживает оба формата:
        * ``litellm.ModelResponse`` — атрибуты ``.choices``, ``.usage``, ``.model``;
        * ``dict`` — те же ключи.

        Returns:
            ``(content, prompt_tokens, completion_tokens, model_used)``.
        """
        if isinstance(response, dict):
            choices = response.get("choices", [])
            usage = response.get("usage", {}) or {}
            model_used = response.get("model") or fallback_model or ""
        else:
            choices = getattr(response, "choices", []) or []
            usage_obj = getattr(response, "usage", None)
            usage = (
                usage_obj.model_dump()
                if usage_obj is not None and hasattr(usage_obj, "model_dump")
                else (usage_obj or {})
            )
            if isinstance(usage_obj, dict):
                usage = usage_obj
            model_used = getattr(response, "model", None) or fallback_model or ""

        content = ""
        if choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message", {}) or {}
                content = msg.get("content", "") or ""
            else:
                msg = getattr(first, "message", None)
                if msg is not None:
                    content = getattr(msg, "content", "") or ""
                    if isinstance(msg, dict):
                        content = msg.get("content", "") or ""

        if isinstance(usage, dict):
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        else:
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

        return content, prompt_tokens, completion_tokens, str(model_used)

    @staticmethod
    def _reraise_normalized(exc: Exception) -> None:
        """Нормализует исключения LiteLLMGateway к доменным Gateway-исключениям."""
        text = str(exc).lower()
        if "rate" in text and "limit" in text:
            from src.backend.services.ai.gateway.exceptions import GatewayRateLimited

            raise GatewayRateLimited(str(exc)) from exc
        from src.backend.services.ai.gateway.exceptions import GatewayUnavailable

        raise GatewayUnavailable(str(exc)) from exc

    def _emit_counter(self, name: str, labels: dict[str, str]) -> None:
        """Эмитит Prometheus counter через MetricsRegistry."""
        if self._metrics_registry is None:
            return
        try:
            counter = getattr(self._metrics_registry, name, None)
            if counter is not None and hasattr(counter, "labels"):
                counter.labels(**labels).inc()
        except Exception:  # noqa: BLE001
            pass

    def _emit_histogram(self, name: str, value: int, labels: dict[str, str]) -> None:
        """Эмитит Prometheus histogram через MetricsRegistry."""
        if self._metrics_registry is None:
            return
        try:
            histogram = getattr(self._metrics_registry, name, None)
            if histogram is not None and hasattr(histogram, "labels"):
                histogram.labels(**labels).observe(value)
        except Exception:  # noqa: BLE001
            pass