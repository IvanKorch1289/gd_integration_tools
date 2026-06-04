"""LiteLLM Gateway — клиент-оболочка над ``litellm`` (К4 MVP, Шаг 1).

Поддерживает:

* :meth:`acompletion` — chat-completion с native streaming через AsyncIterator;
* :meth:`aembedding` — эмбеддинги (для совместимости с RAG-pipeline);
* :meth:`acost_estimate` — оценка стоимости через ``litellm.completion_cost``.

Lazy-импорт ``litellm`` — отсутствие пакета не ломает import (default-OFF).
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from src.backend.core.di.app_state import app_state_singleton
from src.backend.services.ai.gateway.callbacks import (
    CostTrackingCallback,
    FallbackTrackingCallback,
)
from src.backend.services.ai.gateway.exceptions import (
    GatewayRateLimited,
    GatewayUnavailable,
)

__all__ = ("LiteLLMGateway", "get_litellm_gateway")

logger = logging.getLogger(__name__)


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
        from src.backend.core.config.ai_2026 import litellm_gateway_settings as cfg

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

        if self._cost_tracking:
            try:
                callbacks = list(getattr(litellm, "success_callback", []) or [])
                callback = self._select_cost_callback()
                if callback not in callbacks:
                    callbacks.append(callback)
                    litellm.success_callback = callbacks
            except Exception as exc:  # noqa: BLE001
                logger.debug("LiteLLM cost-callback registration failed: %s", exc)

        # Block 2.3 (gap-ai-2.3, ADR-0073): observability fallback events.
        # litellm.failure_callback вызывается на любой provider-failure
        # (timeout / rate-limit / 5xx) ДО внутреннего fallback chain или после
        # его исчерпания. Counter ai_graph_fallback_total{model,reason} даёт
        # сигнал на Grafana alert при деградации primary-провайдера.
        try:
            failure_callbacks = list(getattr(litellm, "failure_callback", []) or [])
            if self._fallback_callback not in failure_callbacks:
                failure_callbacks.append(self._fallback_callback)
                litellm.failure_callback = failure_callbacks
        except Exception as exc:  # noqa: BLE001
            logger.debug("LiteLLM failure-callback registration failed: %s", exc)

        self._litellm = litellm
        return litellm

    def _select_cost_callback(self) -> Any:
        """Wave D.5: LangFuse как primary cost-tracker если включён."""
        try:
            from src.backend.core.config.ai_2026 import langfuse_settings
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
        """Chat-completion. При ``stream=True`` возвращает AsyncIterator чанков."""
        litellm = self._ensure_litellm()
        params: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages,
            "num_retries": self._num_retries,
            "timeout": self._timeout,
            "stream": stream,
            **kwargs,
        }
        if self._fallbacks:
            params.setdefault("fallbacks", self._fallbacks)

        try:
            return await litellm.acompletion(**params)
        except Exception as exc:  # noqa: BLE001
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
        try:
            response = await litellm.aembedding(model=model, input=input_, **kwargs)
        except Exception as exc:  # noqa: BLE001
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

    @staticmethod
    def _raise_normalized(exc: Exception) -> None:
        """Нормализует исключения litellm к доменным."""
        text = str(exc).lower()
        if "rate" in text and "limit" in text:
            raise GatewayRateLimited(str(exc)) from exc
        raise GatewayUnavailable(str(exc)) from exc


@app_state_singleton("litellm_gateway", factory=LiteLLMGateway)
def get_litellm_gateway() -> LiteLLMGateway:  # type: ignore
    """Возвращает singleton :class:`LiteLLMGateway` из ``app.state``."""
