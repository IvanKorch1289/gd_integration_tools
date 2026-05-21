"""LangFuse cost-tracking callback для LiteLLM (Wave D.5).

При ``LANGFUSE_ENABLED=true`` подменяет CostTrackingCallback (ClickHouse
audit) на отправку трейсов в LangFuse через ``langfuse`` Python SDK 2.x.
LangFuse становится единственным источником истины для cost-дашборда.

Все импорты ``langfuse`` lazy — отсутствие пакета не ломает старт
(default-OFF).

K6 Wave 1: добавлена фабрика ``get_langfuse_callback`` с переключением
на :class:`~langfuse_callback_v3.LangFuseCallbackV3` при
``feature_flags.langfuse_v3 = True``.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from src.backend.core.config.features import feature_flags
except ImportError:  # features.py появится в merge с master

    class _FallbackFlags:
        """Заглушка feature-flags при отсутствии модуля features.py."""

        langfuse_v3: bool = False

    feature_flags = _FallbackFlags()  # type: ignore[assignment]

logger = logging.getLogger(__name__)

__all__ = ("LangFuseCostCallback", "get_langfuse_callback")


class LangFuseCostCallback:
    """LiteLLM-callback: response → LangFuse trace/generation."""

    def __init__(self) -> None:
        self._lf: Any = None
        self._inited = False

    def _ensure_client(self) -> Any:
        if self._inited:
            return self._lf
        self._inited = True
        try:
            from langfuse import Langfuse  # type: ignore[import-not-found]

            from src.backend.core.config.ai_2026 import langfuse_settings

            if not langfuse_settings.enabled:
                return None
            self._lf = Langfuse(
                host=langfuse_settings.host or None,
                public_key=langfuse_settings.public_key or None,
                secret_key=langfuse_settings.secret_key or None,
                flush_at=langfuse_settings.flush_at,
            )
            return self._lf
        except Exception as exc:  # noqa: BLE001
            logger.debug("LangFuse client init skipped: %s", exc)
            self._lf = None
            return None

    def __call__(
        self,
        kwargs: dict[str, Any] | None,
        response_obj: Any,
        start_time: Any = None,
        end_time: Any = None,
    ) -> None:
        """LiteLLM success-callback signature."""
        client = self._ensure_client()
        if client is None:
            return
        try:
            kwargs = kwargs or {}
            model = str(kwargs.get("model") or "unknown")
            tenant = (kwargs.get("metadata") or {}).get("tenant") or "default"
            route = (kwargs.get("metadata") or {}).get("route") or kwargs.get(
                "litellm_call_id"
            )

            trace_name = f"llm.{_provider_from_model(model)}"
            trace = client.trace(
                name=trace_name, metadata={"tenant": tenant, "route": route}
            )
            generation = getattr(trace, "generation", None)
            if generation is None:
                return
            generation(
                model=model,
                input=kwargs.get("messages"),
                output=_extract_output(response_obj),
                usage=_extract_usage(response_obj),
                metadata={
                    "cost_usd": _extract_cost(response_obj),
                    "start_time": str(start_time) if start_time else None,
                    "end_time": str(end_time) if end_time else None,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("LangFuseCostCallback emit failed: %s", exc)


def _provider_from_model(model: str) -> str:
    if "/" in model:
        return model.split("/", 1)[0]
    return "openai"


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
        "total_tokens": getattr(usage, "total_tokens", 0),
    }


def _extract_output(response_obj: Any) -> str | None:
    choices = getattr(response_obj, "choices", None)
    if choices is None and isinstance(response_obj, dict):
        choices = response_obj.get("choices") or []
    if not choices:
        return None
    first = choices[0]
    message = getattr(first, "message", None)
    if message is None and isinstance(first, dict):
        message = first.get("message")
    if message is None:
        return None
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return content


def _extract_cost(response_obj: Any) -> float:
    for attr in ("response_cost", "_response_cost"):
        value = getattr(response_obj, attr, None)
        if value:
            try:
                return float(value)
            except TypeError, ValueError:
                return 0.0
    if isinstance(response_obj, dict):
        return float(response_obj.get("response_cost", 0.0) or 0.0)
    return 0.0


def get_langfuse_callback() -> Any:
    """Фабрика LangFuse callback с переключением по feature-flag.

    При ``feature_flags.langfuse_v3 = True`` (FEATURE_LANGFUSE_V3=true)
    возвращает :class:`~langfuse_callback_v3.LangFuseCallbackV3` (OTEL-native SDK 3.x).
    В противном случае возвращает :class:`LangFuseCostCallback` (SDK 2.x, default).

    Returns:
        Экземпляр callback, реализующего LiteLLM success-callback сигнатуру.

    Note:
        v2 ветка активна по умолчанию (default-OFF для langfuse_v3).
        Cutover default-ON — отдельный PR после staging smoke-тестов.
    """
    if feature_flags.langfuse_v3:
        try:
            from src.backend.services.ai.gateway.langfuse_callback_v3 import (
                LangFuseCallbackV3,
            )

            return LangFuseCallbackV3()
        except Exception as exc:  # noqa: BLE001
            logger.warning("LangFuse v3 callback недоступен, fallback на v2: %s", exc)
    return LangFuseCostCallback()
