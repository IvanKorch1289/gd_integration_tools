"""Cost-tracking callback для LiteLLM (Шаг 1 MVP).

LiteLLM поддерживает success/failure callbacks (см. litellm.success_callback).
В MVP мы регистрируем тонкий callback, который при наличии usage-поля в
response пишет cost в :class:`AgentMetricsService` через ``record_cost``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("CostTrackingCallback", "FallbackTrackingCallback")


class CostTrackingCallback:
    """Тонкий callback: response → AgentMetricsService.record_cost."""

    def __init__(self) -> None:
        self._metrics: Any = None

    def _ensure_metrics(self) -> Any:
        if self._metrics is not None:
            return self._metrics
        try:
            from src.backend.services.ai.metrics import get_agent_metrics_service

            self._metrics = get_agent_metrics_service()
        except Exception as exc:  # noqa: BLE001
            logger.debug("CostTrackingCallback: metrics unavailable: %s", exc)
            self._metrics = False
        return self._metrics

    def __call__(
        self,
        kwargs: dict[str, Any] | None,
        response_obj: Any,
        start_time: Any = None,
        end_time: Any = None,
    ) -> None:
        """LiteLLM-совместимая сигнатура success-callback.

        Args:
            kwargs: ``call kwargs`` (содержит ``model``, ``messages``).
            response_obj: ответ провайдера (с ``usage`` / ``response_cost``).
            start_time: начало вызова (не используется, оставлено для API).
            end_time: конец вызова.
        """
        metrics = self._ensure_metrics()
        if metrics in (None, False):
            return

        model = (kwargs or {}).get("model", "unknown")
        provider = self._provider_from_model(model)

        cost_usd = self._extract_cost(response_obj)
        if cost_usd > 0:
            try:
                metrics.record_cost(provider=provider, model=model, cost_usd=cost_usd)
            except Exception as exc:  # noqa: BLE001
                logger.debug("CostTrackingCallback: record_cost failed: %s", exc)

        usage = self._extract_usage(response_obj)
        if usage:
            try:
                metrics.record_tokens(
                    provider=provider,
                    model=model,
                    input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                    output_tokens=int(usage.get("completion_tokens", 0) or 0),
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("CostTrackingCallback: record_tokens failed: %s", exc)

    @staticmethod
    def _provider_from_model(model: str) -> str:
        """``openai/gpt-4o`` → ``openai``; ``gpt-4o`` → ``openai`` (default)."""
        if "/" in model:
            return model.split("/", 1)[0]
        return "openai"

    @staticmethod
    def _extract_cost(response_obj: Any) -> float:
        for attr in ("response_cost", "_response_cost"):
            value = getattr(response_obj, attr, None)
            if value:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return 0.0
        if isinstance(response_obj, dict):
            return float(response_obj.get("response_cost", 0.0) or 0.0)
        return 0.0

    @staticmethod
    def _extract_usage(response_obj: Any) -> dict[str, Any] | None:
        usage = getattr(response_obj, "usage", None)
        if usage is None and isinstance(response_obj, dict):
            usage = response_obj.get("usage")
        if usage is None:
            return None
        if hasattr(usage, "model_dump"):
            return usage.model_dump()
        if isinstance(usage, dict):
            return usage
        return {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
        }


class FallbackTrackingCallback:
    """Block 2.3 (gap-ai-2.3, ADR-0073): track LiteLLM provider-failure events.

    Регистрируется в ``litellm.failure_callback`` через
    :class:`LiteLLMGateway._ensure_litellm`. Каждое provider-failure
    (timeout, 5xx, rate-limit, network-error) инкрементирует Prometheus
    counter ``ai_graph_fallback_total{model, reason}``.

    Use case:
        Метрика отображается на Grafana dashboard "AI Provider Health" —
        алерт ``rate(ai_graph_fallback_total[5m]) > 0`` сигнализирует
        деградацию primary-провайдера. При litellm native fallback chain
        (см. ``LiteLLMGatewaySettings.fallback_models``) — counter растёт
        с label ``model=<primary>`` до переключения на secondary.
    """

    def __init__(self) -> None:
        self._counter: Any = None
        self._initialized: bool = False

    def _ensure_counter(self) -> Any:
        """Lazy-resolve Prometheus counter через metrics_registry."""
        if self._initialized:
            return self._counter
        self._initialized = True
        try:
            from src.backend.infrastructure.observability.metrics_registry import (
                metrics_registry,
            )

            self._counter = metrics_registry.counter(
                "ai_graph_fallback_total",
                "LiteLLM provider-failure events (для алертов и fallback observability)",
                labels=("model", "reason"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("FallbackTrackingCallback: counter unavailable: %s", exc)
            self._counter = False
        return self._counter

    def __call__(
        self,
        kwargs: dict[str, Any] | None,
        exception: Any = None,
        start_time: Any = None,
        end_time: Any = None,
    ) -> None:
        """LiteLLM-совместимая сигнатура failure-callback.

        Args:
            kwargs: ``call kwargs`` (содержит ``model``, ``messages``).
            exception: Исключение от провайдера (timeout / 5xx / rate-limit).
            start_time: Начало вызова.
            end_time: Конец вызова.
        """
        counter = self._ensure_counter()
        if counter in (None, False):
            return

        model = str((kwargs or {}).get("model", "unknown"))
        reason = type(exception).__name__ if exception is not None else "unknown"
        try:
            counter.labels(model=model, reason=reason).inc()
        except Exception as exc:  # noqa: BLE001
            logger.debug("FallbackTrackingCallback: counter inc failed: %s", exc)
