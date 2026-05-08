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
from src.backend.services.ai.gateway.callbacks import CostTrackingCallback
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
    ) -> None:
        from src.backend.core.config.ai_2026 import litellm_gateway_settings as cfg

        self._default_model = default_model or cfg.default_model
        self._fallbacks = list(fallback_models or cfg.fallback_models)
        self._num_retries = num_retries if num_retries is not None else cfg.num_retries
        self._timeout = request_timeout if request_timeout is not None else cfg.request_timeout
        self._cost_tracking = cost_tracking if cost_tracking is not None else cfg.cost_tracking
        self._enabled = cfg.enabled
        self._litellm: Any = None
        self._cost_callback = CostTrackingCallback()

    def _ensure_litellm(self) -> Any:
        """Lazy-import litellm. Поднимает GatewayUnavailable если пакет не установлен."""
        if self._litellm is not None:
            return self._litellm
        if not self._enabled:
            raise GatewayUnavailable(
                "LiteLLMGateway отключён (LITELLM_ENABLED=false)."
            )
        try:
            import litellm  # type: ignore[import-not-found]
        except ImportError as exc:
            raise GatewayUnavailable(
                "Пакет 'litellm' не установлен — добавьте extra '[ai-2026]'."
            ) from exc

        if self._cost_tracking:
            try:
                callbacks = list(getattr(litellm, "success_callback", []) or [])
                if self._cost_callback not in callbacks:
                    callbacks.append(self._cost_callback)
                    litellm.success_callback = callbacks
            except Exception as exc:  # noqa: BLE001
                logger.debug("LiteLLM cost-callback registration failed: %s", exc)

        self._litellm = litellm
        return litellm

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
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        """Удобный wrapper над :meth:`acompletion` с ``stream=True``."""
        result = await self.acompletion(
            messages, model=model, stream=True, **kwargs
        )
        async for chunk in result:
            yield chunk

    async def aembedding(
        self,
        input_: list[str],
        *,
        model: str = "text-embedding-3-small",
        **kwargs: Any,
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
def get_litellm_gateway() -> LiteLLMGateway:
    """Возвращает singleton :class:`LiteLLMGateway` из ``app.state``."""
