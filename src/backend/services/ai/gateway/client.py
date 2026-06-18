"""LiteLLM Gateway — клиент-оболочка над ``litellm`` (К4 MVP, Шаг 1).

Поддерживает:

* :meth:`acompletion` — chat-completion с native streaming через AsyncIterator;
* :meth:`aembedding` — эмбеддинги (для совместимости с RAG-pipeline);
* :meth:`acost_estimate` — оценка стоимости через ``litellm.completion_cost``.

Lazy-импорт ``litellm`` — отсутствие пакета не ломает import (default-OFF).
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from src.backend.core.ai.errors import GatewayRateLimited, GatewayUnavailable
from src.backend.core.di.app_state import app_state_singleton
from src.backend.core.logging import get_logger
from src.backend.services.ai.gateway.callbacks import (
    CostTrackingCallback,
    FallbackTrackingCallback,
)

__all__ = ("LiteLLMGateway", "get_litellm_gateway")

logger = get_logger(__name__)


class LiteLLMGateway:
    """Тонкий async-клиент поверх ``litellm`` с cost-callback и fallback."""

    def __init__(
        self,
        default_model: str | None = None,
        fallback_models: list[str] | None = None,
        num_retries: int | None = None,
        request_timeout: float | None = None,
        cost_tracking: bool | None = None,
        model_registry: Any | None = None,
    ) -> None:
        from src.backend.core.config.ai_stack import litellm_gateway_settings as cfg

        self._default_model = default_model or cfg.default_model
        self._fallbacks = list(fallback_models or cfg.fallback_models)
        self._num_retries = num_retries if num_retries is not None else cfg.num_retries
        self._timeout = (
            request_timeout if request_timeout is not None else cfg.request_timeout
        )
        self._cost_tracking = (
            cost_tracking if cost_tracking is not None else cfg.cost_tracking
        )
        self._enabled = cfg.enabled
        self._litellm: Any = None
        self._cost_callback = CostTrackingCallback()
        self._fallback_callback = FallbackTrackingCallback()
        # ── W2: model registry для dynamic routing ───────────────────────────
        self._model_registry = model_registry

    @property
    def model_registry(self) -> Any:
        """ModelRegistryAdapter для dynamic routing. Может быть None (default-OFF)."""
        return self._model_registry

    async def find_model_by_capabilities(
        self,
        *,
        vision: bool | None = None,
        function_calling: bool | None = None,
        streaming: bool | None = None,
        min_max_tokens: int | None = None,
        latency_tier: str | None = None,
        preferred_provider: str | None = None,
    ) -> str | None:
        """Находит модель по capability-тегам через model registry.

        Если registry недоступен — возвращает ``default_model``.
        """
        registry = self.model_registry
        if registry is None:
            return self._default_model

        try:
            records = await registry.list_models()
            for rec in records:
                if rec.match_capabilities(
                    vision=vision,
                    function_calling=function_calling,
                    streaming=streaming,
                    min_max_tokens=min_max_tokens,
                    latency_tier=latency_tier,
                ):
                    if preferred_provider is None or preferred_provider in rec.tags.get(
                        "provider", ""
                    ):
                        return f"{rec.tags.get('provider', 'openai')}/{rec.name}"
            return self._default_model
        except Exception:  # noqa: BLE001
            return self._default_model

    def _ensure_litellm(self) -> Any:
        """Lazy-import litellm. Поднимает GatewayUnavailable если пакет не установлен."""
        if self._litellm is not None:
            return self._litellm
        if not self._enabled:
            raise GatewayUnavailable("LiteLLMGateway отключён (LITELLM_ENABLED=false).")
        try:
            import litellm  # type: ignore[import-not-found]
        except ImportError as exc:
            raise GatewayUnavailable(
                "Пакет 'litellm' не установлен — добавьте extra '[ai-2026]'."
            ) from exc

        self._litellm = litellm
        return litellm

    def _select_cost_callback(self) -> Any:
        """Wave D.5: LangFuse как primary cost-tracker если включён."""
        try:
            from src.backend.core.config.ai_stack import langfuse_settings
        except Exception as _:  # noqa: BLE001
            return self._cost_callback
        if not langfuse_settings.enabled:
            return self._cost_callback
        try:
            from src.backend.services.ai.gateway.langfuse_callback_v3 import (
                get_langfuse_callback,
            )

            return get_langfuse_callback()
        except Exception as exc:  # noqa: BLE001
            logger.debug("LangFuse callback selection failed: %s", exc)
            return self._cost_callback

    async def acompletion(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Chat-completion. При ``stream=True`` возвращает AsyncIterator чанков.

        S164 W1 (AI-R4): Circuit Breaker guard. Per-service litellm имеет
        встроенный retry (num_retries), но не имеет CB — repeated failures
        не cascade'ят в cost-control. CB открывается после 5 consecutive
        failures → _raise_normalized превращает CircuitOpen в
        GatewayUnavailable.
        """
        litellm = self._ensure_litellm()
        litellm_exc = litellm.exceptions
        params: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages,
            "num_retries": self._num_retries,
            "timeout": self._timeout,
            "stream": stream,
            "success_callback": [self._select_cost_callback()],
            "failure_callback": [self._fallback_callback],
            **kwargs,
        }
        if self._fallbacks:
            params.setdefault("fallbacks", self._fallbacks)

        # S164 W1 (AI-R4): Circuit Breaker per gateway instance.
        from src.backend.core.resilience.breaker import (
            BreakerSpec,
            get_breaker_registry,
        )

        if not hasattr(self, "_cb"):
            self._cb = get_breaker_registry().get_or_create(
                "litellm_gateway",
                BreakerSpec(
                    name="litellm_gateway",
                    failure_threshold=5,
                    recovery_timeout=30.0,
                ),
            )
        async with self._cb.guard():
            try:
                return await litellm.acompletion(**params)
            except (
                litellm_exc.RateLimitError,
                litellm_exc.ServiceUnavailableError,
                litellm_exc.Timeout,
                litellm_exc.APIError,
                litellm_exc.BadRequestError,
                litellm_exc.AuthenticationError,
                asyncio.TimeoutError,
                GatewayRateLimited,
                GatewayUnavailable,
            ) as exc:
                self._raise_normalized(exc)

    async def astream_completion(
        self, messages: list[dict[str, Any]], *, model: str | None = None, **kwargs: Any
    ) -> AsyncIterator[Any]:
        """Удобный wrapper над :meth:`acompletion` с ``stream=True``."""
        result = await self.acompletion(messages, model=model, stream=True, **kwargs)
        async for chunk in result:
            yield chunk

    async def aembedding(
        self, input_: list[str], *, model: str = "text-embedding-3-small", **kwargs: Any
    ) -> list[list[float]]:
        """Эмбеддинги для RAG-pipeline. Возвращает list[list[float]]."""
        litellm = self._ensure_litellm()
        litellm_exc = litellm.exceptions
        params: dict[str, Any] = {
            "model": model,
            "input": input_,
            "success_callback": [self._select_cost_callback()],
            "failure_callback": [self._fallback_callback],
            **kwargs,
        }
        try:
            response = await litellm.aembedding(**params)
        except (
            litellm_exc.RateLimitError,
            litellm_exc.ServiceUnavailableError,
            litellm_exc.Timeout,
            litellm_exc.APIError,
            litellm_exc.BadRequestError,
            litellm_exc.AuthenticationError,
            asyncio.TimeoutError,
            GatewayRateLimited,
            GatewayUnavailable,
        ) as exc:
            self._raise_normalized(exc)

        data = getattr(response, "data", None)
        if data is None and isinstance(response, dict):
            data = response.get("data", [])
        vectors: list[list[float]] = []
        for item in data or []:
            embedding = (
                item.get("embedding")
                if isinstance(item, dict)
                else getattr(item, "embedding", None)
            )
            if embedding is not None:
                vectors.append(list(embedding))
        return vectors

    async def acost_estimate(
        self,
        *,
        model: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> float:
        """Оценка стоимости вызова через ``litellm.completion_cost``."""
        litellm = self._ensure_litellm()
        try:
            return float(
                litellm.cost_calculator.completion_cost(
                    model=model or self._default_model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("acost_estimate failed: %s", exc)
            return 0.0

    async def healthcheck(self, *, model: str | None = None) -> bool:
        """S164 W2 (AI-R4 healthcheck): lightweight Liveness check.

        Calls acompletion с минимальными tokens. ``True`` если gateway
        отвечает в timeout, ``False`` при любой ошибке (недоступен,
        rate-limited, circuit-open, и т.п.).

        Args:
            model: Модель для healthcheck (default = ``self._default_model``).

        Returns:
            ``True`` если gateway operational, ``False`` otherwise.
        """
        try:
            await self.acompletion(
                messages=[{"role": "user", "content": "ping"}],
                model=model,
                max_tokens=1,
                timeout=5.0,
            )
            return True
        except Exception as exc:
            logger.debug("litellm_gateway.healthcheck failed: %s", exc)
            return False

    def _raise_normalized(self, exc: Exception) -> None:
        """Нормализует исключения litellm к доменным."""
        if isinstance(exc, (GatewayRateLimited, GatewayUnavailable)):
            raise exc
        litellm_exc = getattr(self._litellm, "exceptions", None)
        if litellm_exc is None:
            raise GatewayUnavailable(str(exc)) from exc
        if isinstance(exc, litellm_exc.RateLimitError):
            raise GatewayRateLimited(str(exc)) from exc
        if isinstance(
            exc,
            (
                litellm_exc.ServiceUnavailableError,
                litellm_exc.Timeout,
                asyncio.TimeoutError,
            ),
        ):
            raise GatewayUnavailable(str(exc)) from exc
        raise GatewayUnavailable(str(exc)) from exc


@app_state_singleton("litellm_gateway", factory=LiteLLMGateway)
def get_litellm_gateway() -> LiteLLMGateway:  # type: ignore
    """Возвращает singleton :class:`LiteLLMGateway` из ``app.state``."""
