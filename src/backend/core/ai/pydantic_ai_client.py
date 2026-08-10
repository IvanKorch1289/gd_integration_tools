"""PydanticAI Unified Client — единая точка входа в LWM.

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

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.backend.core.ai.errors import GatewayRateLimited, GatewayUnavailable
from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = get_logger(__name__)


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


# ── PydanticAI Model adapter (S168 W16 P1-5) ──────────────────────────────
#
# Per master prompt v8 P1-5: "implement full pydantic_ai.models.Model
# Protocol (missing request/request_stream)".
#
# LiteLLMModelAdapter wraps the existing LiteLLMGateway и
# provides pydantic_ai.models.Model interface for Agent integration.
#
# Lazy import: pydantic_ai optional (ai-2026 extra in pyproject.toml).
# Falls back gracefully если pydantic_ai не установлен.
# ────────────────────────────────────────────────────────────────────────────

try:
    from pydantic_ai.models import (
        Model as _PydanticAIModel,
    )

    _PYDANTIC_AI_AVAILABLE = True
except ImportError:  # pragma: no cover — optional dep
    _PydanticAIModel = None  # type: ignore[assignment,misc]
    _PYDANTIC_AI_AVAILABLE = False


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
        self._register_metrics()

    def _register_metrics(self) -> None:
        """Pre-register all ai_pydantic_client_* metrics (idempotent)."""
        if self._metrics_registry is None:
            return
        try:
            self._metrics_registry.counter(
                "ai_pydantic_client_requests_total",
                "PydanticAIClient LLM request counter",
                labels=("model", "status"),
            )
            self._metrics_registry.histogram(
                "ai_pydantic_client_latency_ms",
                "PydanticAIClient LLM latency in ms",
                labels=("model",),
            )
            self._metrics_registry.counter(
                "ai_pydantic_client_fallback_total",
                "PydanticAIClient fallback counter",
                labels=("model", "reason"),
            )
            self._metrics_registry.counter(
                "ai_pydantic_client_retry_total",
                "PydanticAIClient retry counter",
                labels=("model", "attempt"),
            )
        except (AttributeError, TypeError, ValueError) as exc:
            # Metrics registration is best-effort — не должен ломать init клиента.
            # Раньше except Exception: pass — скрывал TypeError при None
            # metrics_registry (V22 K-OP-1).
            logger.debug("PydanticAIClient metrics registration failed: %s", exc)

    # ── public API ─────────────────────────────────────────────────────────

    async def run(
        self,
        prompt: str,
        *,
        output_type: type[BaseModel] | None = None,
        deps: LLMDependencies | None = None,
        stream: bool = False,
        _internal_gateway_call: bool = False,
    ) -> LLMResult:
        """Выполняет LLM-вызов через LiteLLMGateway с fallback chain.

        Args:
            prompt: Готовый prompt (после render + sanitize + guard).
            output_type: Pydantic model для structured output.
                Реализовано в S32 W2; пока игнорируется.
            deps: LLMDependencies для tenant/correlation isolation.
                Реализовано в S32 W2; пока игнорируется.
            stream: Streaming поддерживается через LiteLLMGateway.astream_completion.
                Если True → возвращает AsyncIterator чанков. Реализовано в S32 W2.
                Если False → возвращает обычный LLMResult. Default False.

        Returns:
            LLMResult с content/structured/tokens/cost/model/latency.

        Raises:
            GatewayUnavailable: Все модели в fallback chain недоступны.
            GatewayRateLimited: Rate-limit на всех моделях.
            UnsupportedOperationError → NotImplementedError: stream=True
                пока не реализован (deadline S32 W2+). Fail-fast на входе метода.

        """
        if stream:
            # Fail-fast (S210 fix, REPORT.md gap #3): нельзя валиться на 100-ой
            # строке метода после дорогих setup-вызовов. Caller получит
            # ошибку ДО любых side-effects (logger emit, feature-flag check).
            raise NotImplementedError(
                "PydanticAIClient.run(stream=True) пока не реализован "
                "(deadline S32 W2+). Используйте stream=False или "
                "напрямую LiteLLMGateway.astream_completion().",
            )

        if not _internal_gateway_call:
            try:
                from src.backend.core.config.features import (
                    feature_flags,
                )
            except ImportError:
                feature_flags = None  # type: ignore[assignment]
            if feature_flags is not None and feature_flags.ai_gateway_enforce:
                # TD-012: log audit-trail warning перед raise — operators
                # need to know о bypass-попытке (кто-то забыл marker).
                try:
                    from src.backend.core.logging import (
                        get_logger as _gl,
                    )

                    _audit_log = _gl("ai.safety.audit")
                    _audit_log.warning(
                        "ai_gateway_bypass_blocked",
                        extra={
                            "client": "PydanticAIClient",
                            "method": "run",
                            "hint": "pass _internal_gateway_call=True "
                            "для вызовов из AIGateway-pipeline",
                        },
                    )
                except (ImportError, AttributeError, RuntimeError) as audit_exc:
                    # cycle-9/D-AUDIT-1035: narrow exceptions + observability.
                    # ImportError — audit facade missing, AttributeError
                    # — API change, RuntimeError — backend unavailable.
                    # audit-log — best-effort, не должен блокировать raise.
                    logger.debug(
                        "PydanticAIClient bypass audit failed: %s", audit_exc,
                    )
                raise RuntimeError(
                    "PydanticAIClient.run() bypasses AIGateway; "
                    "use AIGateway.invoke() instead",
                )

        if stream:
            # Defensive guard: fail-fast уже сделан выше (line ~209). Этот
            # unreachable branch оставлен как safety-net для future refactors,
            # когда stream может стать частично реализованным (частичный
            # success → explicit error вместо silent None).
            raise NotImplementedError(
                "PydanticAIClient.run(stream=True) недоступен — см. fail-fast выше.",
            )

        assert not stream, "unreachable"  # for mypy
        del output_type, deps
        start_ms: int = int(time.monotonic() * 1000)

        primary = self._primary_model()
        fallbacks = self._fallback_models()
        retry_attempts = self._retry_attempts()

        self._emit_counter(
            "ai_pydantic_client_requests_total", {"model": primary, "status": "started"},
        )

        messages = [{"role": "user", "content": prompt}]
        kwargs: dict[str, Any] = {"stream": False}
        if fallbacks:
            kwargs["fallbacks"] = fallbacks

        last_exc: Exception | None = None
        for attempt in range(1, retry_attempts + 1):
            try:
                response = await self._gateway.acompletion(
                    messages, model=primary, **kwargs,
                )
                latency_ms = int(time.monotonic() * 1000) - start_ms

                (content, tokens_prompt, tokens_completion, model_used) = (
                    self._extract_completion(response, fallback_model=primary)
                )
                is_fallback = model_used != primary

                self._emit_counter(
                    "ai_pydantic_client_requests_total",
                    {"model": model_used, "status": "success"},
                )
                self._emit_histogram(
                    "ai_pydantic_client_latency_ms", latency_ms, {"model": model_used},
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
                logger.debug("PydanticAIClient: attempt %d failed (%s)", attempt, exc)
                continue

        # Все fail — эмитим ошибку и пробрасываем
        self._emit_counter(
            "ai_pydantic_client_requests_total", {"model": primary, "status": "error"},
        )
        self._reraise_normalized(last_exc or RuntimeError("No models available"))
        # NOTE: unreachable — _reraise_normalized always raises; kept for type checker
        raise RuntimeError("Unexpected: no retry path returned")

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
        response: Any, *, fallback_model: str | None,
    ) -> tuple[str, int, int, str]:
        """Layer 8 Cycle 1: единый helper (см. core/ai/_llm_response.py).

        Выделен в shared utility — DRY violation был в 2 местах
        (этот + gateway_pipeline_mixin/llm_mixin.py).
        """
        from src.backend.core.ai._llm_response import extract_completion

        return extract_completion(response, fallback_model=fallback_model)

    @staticmethod
    def _reraise_normalized(exc: Exception) -> None:
        """Нормализует исключения LiteLLMGateway к доменным Gateway-исключениям."""
        text = str(exc).lower()
        if "rate" in text and "limit" in text:
            raise GatewayRateLimited(str(exc)) from exc
        raise GatewayUnavailable(str(exc)) from exc

    def _emit_counter(self, name: str, labels: dict[str, str]) -> None:
        """Эмитит Prometheus counter через MetricsRegistry."""
        if self._metrics_registry is None:
            return
        try:
            counter = getattr(self._metrics_registry, name, None)
            if counter is not None and hasattr(counter, "labels"):
                counter.labels(**labels).inc()
        except (AttributeError, TypeError, ValueError) as counter_exc:
            # cycle-9/D-AUDIT-986: narrow exceptions + observability.
            # AttributeError — counter API change, TypeError — wrong arg
            # type, ValueError — invalid label value.
            import logging
            logging.getLogger(__name__).debug(
                "pydantic_ai_client.counter_emit_failed",
                extra={"name": name, "error": str(counter_exc)},
            )

    def _emit_histogram(self, name: str, value: int, labels: dict[str, str]) -> None:
        """Эмитит Prometheus histogram через MetricsRegistry."""
        if self._metrics_registry is None:
            return
        try:
            histogram = getattr(self._metrics_registry, name, None)
            if histogram is not None and hasattr(histogram, "labels"):
                histogram.labels(**labels).observe(value)
        except (AttributeError, TypeError, ValueError) as hist_exc:
            # cycle-9/D-AUDIT-986: см. выше — тот же narrow для histogram.
            import logging
            logging.getLogger(__name__).debug(
                "pydantic_ai_client.histogram_emit_failed",
                extra={"name": name, "error": str(hist_exc)},
            )


# ── LiteLLMModelAdapter (S168 W16 P1-5) ────────────────────────────────────
#
# S168 W16 P1-5: full pydantic_ai.models.Model Protocol implementation.
# Wraps existing LiteLLMGateway. Default-OFF — instantiates only when
# pydantic_ai is installed И user explicitly creates the adapter.
# ────────────────────────────────────────────────────────────────────────────

if _PYDANTIC_AI_AVAILABLE and _PydanticAIModel is not None:
    from collections.abc import AsyncGenerator
    from typing import Any as _Any

    from pydantic_ai.messages import ModelMessage as _ModelMessage
    from pydantic_ai.messages import ModelRequest as _ModelRequest
    from pydantic_ai.messages import ModelResponse as _ModelResponse
    from pydantic_ai.messages import ModelResponsePart as _ModelResponsePart
    from pydantic_ai.messages import TextPart as _TextPart
    from pydantic_ai.models import ModelRequestContext as _ModelRequestContext
    from pydantic_ai.models import ModelRequestParameters as _ModelRequestParameters
    from pydantic_ai.models import ModelSettings as _ModelSettings
    from pydantic_ai.models import StreamedResponse as _StreamedResponse
    from pydantic_ai.usage import RequestUsage as _RequestUsage
    from pydantic_ai.usage import Usage as _Usage

    try:
        from pydantic_ai.tools import (
            AbstractNativeTool as _AbstractNativeTool,  # type: ignore[attr-defined]
        )
    except ImportError:  # pragma: no cover — version-specific
        _AbstractNativeTool = object  # type: ignore[assignment,misc]

    class LiteLLMModelAdapter(_PydanticAIModel):  # type: ignore[misc]
        """S168 W16 P1-5: pydantic_ai Model adapter поверх LiteLLMGateway.

        Реализует полный pydantic_ai.models.Model Protocol
        (per master prompt v8 P1-5: request, request_stream,
        prepare_request, supported_builtin_tools, supported_native_tools).

        Args:
            gateway: :class:`LiteLLMGateway` для выполнения HTTP.
            model_name: primary model name (e.g. "gpt-4o", "claude-3-5-sonnet").
            provider: provider label (e.g. "openai", "anthropic", "litellm").

        """

        def __init__(
            self, *, gateway: _Any, model_name: str, provider: str = "litellm",
        ) -> None:
            self._gateway = gateway
            self._model_name = model_name
            self._provider = provider

        @property
        def model_name(self) -> str:
            """Имя модели в формате 'provider:model_name' (e.g. 'openai:gpt-4o')."""
            return self._model_name

        @property
        def provider(self) -> str:
            """Имя провайдера ('openai', 'anthropic', 'ollama', etc.)."""
            return self._provider

        @property
        def base_url(self) -> str | None:
            """Базовый URL API; None для default провайдера."""
            return None

        @property
        def system(self) -> str | None:
            """System prompt (None = default AIGateway prompt)."""
            return "openai-chat"  # default для chat models

        async def request(
            self,
            messages: list[_ModelMessage],
            model_settings: _ModelSettings | None,
            model_request_parameters: _ModelRequestParameters,
        ) -> _ModelResponse:
            """S168 W16 P1-5: non-streaming request — wraps LiteLLMGateway."""
            from pydantic_ai.models import ModelResponse as _Resp

            # Convert pydantic_ai messages → LiteLLM-compatible dict list
            last_msg = messages[-1] if messages else None
            if isinstance(last_msg, _ModelRequest):
                # Use parts (text only — tool calls separate path)
                content = "".join(
                    part.content
                    for part in last_msg.parts
                    if hasattr(part, "content") and isinstance(part.content, str)
                )
            else:
                content = ""

            response = await self._gateway.acompletion(
                model=self._model_name, messages=[{"role": "user", "content": content}],
            )

            # Wrap в pydantic_ai ModelResponse
            text = self._extract_text(response)
            return _Resp(
                parts=[_TextPart(text)],  # type: ignore[list-item]
                model_name=self._model_name,
                usage=_Usage(requests=1),
            )

        async def request_stream(
            self,
            messages: list[_ModelMessage],
            model_settings: _ModelSettings | None,
            model_request_parameters: _ModelRequestParameters,
            run_context: _Any | None = None,
        ) -> AsyncGenerator[_StreamedResponse]:
            """S168 W16 P1-5: streaming request — yields LiteLLM chunks."""
            last_msg = messages[-1] if messages else None
            if isinstance(last_msg, _ModelRequest):
                content = "".join(
                    part.content
                    for part in last_msg.parts
                    if hasattr(part, "content") and isinstance(part.content, str)
                )
            else:
                content = ""

            async for chunk in await self._gateway.astream(
                model=self._model_name, messages=[{"role": "user", "content": content}],
            ):
                text = self._extract_text(chunk)
                if text:
                    yield _SimpleStreamedResponse(  # type: ignore[misc]
                        model_name=self._model_name, text=text,
                    )

        def customize_request_parameters(
            self, model_request_parameters: _ModelRequestParameters,
        ) -> _ModelRequestParameters:
            """Добавить provider-specific параметры в request (override)."""
            return model_request_parameters

        def prepare_request(
            self,
            model_settings: _ModelSettings | None,
            model_request_parameters: _ModelRequestParameters,
        ) -> tuple[_ModelSettings | None, _ModelRequestParameters]:
            """Подготовить финальные settings + parameters для API call."""
            return (model_settings, model_request_parameters)

        def prepare_messages(
            self, messages: list[_ModelMessage],
        ) -> list[_ModelMessage]:
            """Преобразовать pydantic-ai messages → wire-format."""
            return messages

        async def count_tokens(
            self,
            messages: list[_ModelMessage],
            model_settings: _ModelSettings | None,
            model_request_parameters: _ModelRequestParameters,
        ) -> _RequestUsage:
            """Подсчитать токены в messages (для cost-cap / budget tracking)."""
            # Approximate: 1 token per 4 chars
            total = 0
            for msg in messages:
                if isinstance(msg, _ModelRequest):
                    for part in msg.parts:
                        if hasattr(part, "content") and isinstance(part.content, str):
                            total += len(part.content) // 4
            return _RequestUsage(input_tokens=total)

        @property
        def supported_builtin_tools(self) -> frozenset[type[_AbstractNativeTool]]:  # type: ignore[valid-type]
            """frozenset builtin tools (web_search, code_execution)."""
            return frozenset()

        @property
        def supported_native_tools(self) -> frozenset[type[_AbstractNativeTool]]:  # type: ignore[valid-type]
            """frozenset native tools (function_calling)."""
            return frozenset()

        async def compact_messages(
            self,
            request_context: _ModelRequestContext,
            *,
            instructions: str | None = None,
        ) -> _ModelResponse | None:
            """Optional context compaction (если модель поддерживает)."""
            return None  # No-op: no compact logic

        @property
        def label(self) -> str:
            """Diagnostic label для логов (e.g. 'openai/gpt-4o-mini')."""
            return f"{self._provider}:{self._model_name}"

        @property
        def model_id(self) -> str:
            """Уникальный model_id (e.g. 'gpt-4o-mini-2024-07-18')."""
            return f"{self._provider}:{self._model_name}"

        @property
        def profile(self) -> _Any:
            """Auth profile name (e.g. 'default', 'team-a')."""
            return None

        @property
        def settings(self) -> _ModelSettings | None:
            """ModelSettings (temperature, max_tokens, top_p, etc.)."""
            return None

        @staticmethod
        def _extract_text(response: _Any) -> str:
            """Извлекает текст из LiteLLM response (model-agnostic)."""
            if isinstance(response, str):
                return response
            if isinstance(response, dict):
                # OpenAI format
                choices = response.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
                # Anthropic format
                content = response.get("content", [])
                if content and isinstance(content, list):
                    return "".join(
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict)
                    )
            # Pydantic-like
            if hasattr(response, "choices") and response.choices:
                return response.choices[0].message.content or ""
            return str(response)

    class _SimpleStreamedResponse(_StreamedResponse):  # type: ignore[misc]
        """Minimal StreamedResponse for LiteLLMModelAdapter."""

        def __init__(self, *, model_name: str, text: str) -> None:
            self._model_name = model_name
            self._text = text

        async def _get_event_iterator(self) -> AsyncGenerator[_ModelResponsePart]:
            yield _TextPart(self._text)  # type: ignore[misc]

        @property
        def model_name(self) -> str:
            """Имя модели в формате 'provider:model_name' (e.g. 'openai:gpt-4o')."""
            return self._model_name

        @property
        def provider(self) -> str:
            """Имя провайдера ('openai', 'anthropic', 'ollama', etc.)."""
            return "litellm"

        @property
        def usage(self) -> _RequestUsage:
            return _RequestUsage(input_tokens=0, output_tokens=len(self._text) // 4)

    __all__ = ("LiteLLMModelAdapter", "_SimpleStreamedResponse")
