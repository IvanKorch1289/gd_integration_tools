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
        """LiteLLM success-callback signature.

        Block 1.2 (gap-ai-1.2, ADR-0072): при ``LangFuseSettings.sanitize_traces=True``
        (default) input/output/metadata анонимизируются через PII-санитайзер
        перед отправкой в Langfuse. Это закрывает 152-ФЗ compliance gap —
        SaaS-instance Langfuse не получает ФИО/ИНН/СНИЛС клиентов банка.
        """
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

            input_messages = kwargs.get("messages")
            output_text = _extract_output(response_obj)
            generation_metadata: dict[str, Any] = {
                "cost_usd": _extract_cost(response_obj),
                "start_time": str(start_time) if start_time else None,
                "end_time": str(end_time) if end_time else None,
            }
            input_messages, output_text, generation_metadata = _maybe_anonymize(
                input_messages=input_messages,
                output_text=output_text,
                generation_metadata=generation_metadata,
                tenant_id=str(tenant) if tenant else None,
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
                input=input_messages,
                output=output_text,
                usage=_extract_usage(response_obj),
                metadata=generation_metadata,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("LangFuseCostCallback emit failed: %s", exc)


def _maybe_anonymize(
    *,
    input_messages: Any,
    output_text: Any,
    generation_metadata: dict[str, Any],
    tenant_id: str | None,
) -> tuple[Any, Any, dict[str, Any]]:
    """Block 1.2: анонимизирует payload Langfuse через PII-санитайзер.

    Применяет :func:`anonymize_trace_payload` к ``input_messages``,
    ``output_text``, ``generation_metadata`` при включённом
    ``LangFuseSettings.sanitize_traces=True``. Иначе — passthrough.

    ``anonymize_trace_payload`` сам учитывает ``PRESIDIO_PII_ENABLED``:
    при выключенном feature-flag возвращает payload без изменений
    (no-op). Это даёт single source of truth для PII-стека.

    Args:
        input_messages: Список сообщений LLM (input).
        output_text: Текст ответа LLM.
        generation_metadata: Произвольные поля trace.
        tenant_id: Tenant-контекст для audit-event ``pii.anonymized``.

    Returns:
        Кортеж (input, output, metadata) после анонимизации (или без неё).
    """
    try:
        from src.backend.core.config.ai_2026 import langfuse_settings
    except Exception as _:  # noqa: BLE001 — конфиг недоступен в degenerate setup
        return input_messages, output_text, generation_metadata
    if not langfuse_settings.sanitize_traces:
        return input_messages, output_text, generation_metadata

    from src.backend.services.ai.gateway.langfuse_pii_callback import (
        anonymize_trace_payload,
    )

    sanitized_input = anonymize_trace_payload(
        {"_messages": input_messages} if input_messages is not None else None,
        tenant_id=tenant_id,
    )
    new_input = (
        sanitized_input.get("_messages")
        if isinstance(sanitized_input, dict)
        else input_messages
    )
    sanitized_output = anonymize_trace_payload(
        {"_text": output_text} if output_text is not None else None, tenant_id=tenant_id
    )
    new_output = (
        sanitized_output.get("_text")
        if isinstance(sanitized_output, dict)
        else output_text
    )
    sanitized_metadata = (
        anonymize_trace_payload(generation_metadata, tenant_id=tenant_id)
        or generation_metadata
    )
    return new_input, new_output, sanitized_metadata


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
