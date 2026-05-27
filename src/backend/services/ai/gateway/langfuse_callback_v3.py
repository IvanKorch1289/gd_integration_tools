"""LangFuse 3.x cost-tracking callback для LiteLLM (K6 Wave 1, spike).

Параллельная реализация поверх LangFuse 3.x SDK (OTEL-native).
Активируется только при ``feature_flags.langfuse_v3 = True`` (default-OFF).

Отличия от v2 (``langfuse_callback.py``):
- Трассировка через контекстный менеджер ``langfuse.start_as_current_span`` вместо
  imperative ``client.trace(...).generation(...)``.
- Декоратор ``@langfuse.observe`` для автоматического создания trace-span.
- ``Langfuse`` конструируется без ``flush_at`` (параметр удалён в 3.x; используется
  ``flush_interval`` через глобальную конфигурацию OTEL exporter).
- Импорт ``langfuse`` выполняется lazy (отсутствие пакета не ломает старт).

Использование:
    Через фабрику ``get_langfuse_callback()`` в ``langfuse_callback.py``:

        if feature_flags.langfuse_v3:
            from .langfuse_callback_v3 import LangFuseCallbackV3
            return LangFuseCallbackV3()
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("LangFuseCallbackV3",)


class LangFuseCallbackV3:
    """LiteLLM-callback: response → LangFuse 3.x trace/span.

    Публичный API совпадает с :class:`~langfuse_callback.LangFuseCostCallback`
    (v2), что обеспечивает бесшовную замену в ``_select_cost_callback``.

    Lifecycle:
        1. Первый ``__call__`` → ``_ensure_client()`` → lazy-import + init.
        2. Каждый вызов открывает trace-span через ``langfuse.start_as_current_span``.
        3. Span обогащается метаданными модели, usage и cost.

    Args:
        Нет публичных аргументов — конфигурация через ``langfuse_settings``.
    """

    def __init__(self) -> None:
        """Инициализирует callback без побочных эффектов (lazy-init)."""
        self._lf: Any = None
        self._inited: bool = False

    def _ensure_client(self) -> Any:
        """Lazy-инициализация Langfuse 3.x клиента.

        Returns:
            Экземпляр ``Langfuse`` или ``None``, если пакет недоступен
            либо LangFuse отключён в настройках.
        """
        if self._inited:
            return self._lf
        self._inited = True
        try:
            from langfuse import Langfuse  # type: ignore[import-not-found]

            from src.backend.core.config.ai_2026 import langfuse_settings

            if not langfuse_settings.enabled:
                logger.debug("LangFuse v3 disabled via langfuse_settings.enabled=False")
                return None

            # LangFuse 3.x: flush_at удалён; host/keys как раньше.
            # При отсутствии ключей Langfuse работает в no-op режиме.
            self._lf = Langfuse(
                host=langfuse_settings.host or None,
                public_key=langfuse_settings.public_key or None,
                secret_key=langfuse_settings.secret_key or None,
            )
            return self._lf
        except ImportError:
            logger.debug("LangFuse v3 пакет недоступен — установите 'langfuse>=3'")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.debug("LangFuse v3 client init skipped: %s", exc)
            return None

    def __call__(
        self,
        kwargs: dict[str, Any] | None,
        response_obj: Any,
        start_time: Any = None,
        end_time: Any = None,
    ) -> None:
        """LiteLLM success-callback: отправляет trace в LangFuse 3.x.

        Args:
            kwargs: параметры LiteLLM-вызова (``model``, ``messages``, ``metadata``).
            response_obj: ответ провайдера (с полями ``usage``, ``response_cost``).
            start_time: начало вызова (ISO str или datetime, опционально).
            end_time: конец вызова (опционально).
        """
        client = self._ensure_client()
        if client is None:
            return
        try:
            kwargs = kwargs or {}
            model: str = str(kwargs.get("model") or "unknown")
            metadata: dict[str, Any] = kwargs.get("metadata") or {}
            tenant: str = metadata.get("tenant") or "default"
            route: Any = metadata.get("route") or kwargs.get("litellm_call_id")
            messages: Any = kwargs.get("messages")
            output_text: Any = _extract_output(response_obj)
            span_metadata: dict[str, Any] = {
                "tenant": tenant,
                "route": route,
                "cost_usd": _extract_cost(response_obj),
                "start_time": str(start_time) if start_time else None,
                "end_time": str(end_time) if end_time else None,
            }

            # Block 1.2 (gap-ai-1.2, ADR-0072): анонимизация PII в trace payload.
            messages, output_text, span_metadata = _maybe_anonymize_v3(
                input_messages=messages,
                output_text=output_text,
                span_metadata=span_metadata,
                tenant_id=str(tenant) if tenant else None,
            )

            trace_name = f"llm.{_provider_from_model(model)}"

            # LangFuse 3.x: используем start_as_current_span для OTEL-совместимости.
            with client.start_as_current_span(name=trace_name, input=messages) as span:
                span.update(
                    model=model,
                    output=output_text,
                    usage=_to_langfuse_usage(_extract_usage(response_obj)),
                    metadata=span_metadata,
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("LangFuseCallbackV3 emit failed: %s", exc)


def _maybe_anonymize_v3(
    *,
    input_messages: Any,
    output_text: Any,
    span_metadata: dict[str, Any],
    tenant_id: str | None,
) -> tuple[Any, Any, dict[str, Any]]:
    """Block 1.2: анонимизирует PII в trace payload до отправки в Langfuse 3.x.

    Зеркало :func:`langfuse_callback._maybe_anonymize` для SDK 3.x ветки.
    Учитывает ``LangFuseSettings.sanitize_traces`` и
    ``feature_flags.presidio_pii_enabled`` (single source of truth через
    :func:`anonymize_trace_payload`).
    """
    try:
        from src.backend.core.config.ai_2026 import langfuse_settings
    except Exception as _:  # noqa: BLE001
        return input_messages, output_text, span_metadata
    if not langfuse_settings.sanitize_traces:
        return input_messages, output_text, span_metadata

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
        {"_text": output_text} if output_text is not None else None,
        tenant_id=tenant_id,
    )
    new_output = (
        sanitized_output.get("_text")
        if isinstance(sanitized_output, dict)
        else output_text
    )
    sanitized_metadata = (
        anonymize_trace_payload(span_metadata, tenant_id=tenant_id) or span_metadata
    )
    return new_input, new_output, sanitized_metadata


# ─── Вспомогательные функции ────────────────────────────────────────────────


def _provider_from_model(model: str) -> str:
    """Извлекает имя провайдера из строки модели.

    Args:
        model: строка вида ``"openai/gpt-4o"`` или ``"gpt-4o"``.

    Returns:
        Имя провайдера (``"openai"`` по умолчанию).
    """
    if "/" in model:
        return model.split("/", 1)[0]
    return "openai"


def _extract_usage(response_obj: Any) -> dict[str, Any] | None:
    """Извлекает usage-словарь из ответа LiteLLM.

    Args:
        response_obj: объект ответа провайдера.

    Returns:
        Словарь с ключами ``prompt_tokens``, ``completion_tokens``,
        ``total_tokens`` или ``None`` если usage недоступен.
    """
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


def _to_langfuse_usage(usage: dict[str, Any] | None) -> dict[str, int] | None:
    """Преобразует usage-словарь в формат LangFuse 3.x (``input``/``output``).

    Args:
        usage: словарь с ``prompt_tokens``/``completion_tokens`` или ``None``.

    Returns:
        Словарь ``{"input": N, "output": M, "total": T}`` или ``None``.
    """
    if usage is None:
        return None
    return {
        "input": int(usage.get("prompt_tokens", 0) or 0),
        "output": int(usage.get("completion_tokens", 0) or 0),
        "total": int(usage.get("total_tokens", 0) or 0),
    }


def _extract_output(response_obj: Any) -> str | None:
    """Извлекает текст первого choice из ответа.

    Args:
        response_obj: объект ответа провайдера.

    Returns:
        Текст содержимого или ``None``.
    """
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
    """Извлекает стоимость вызова в USD из ответа провайдера.

    Args:
        response_obj: объект ответа провайдера.

    Returns:
        Стоимость в USD (0.0 если недоступна).
    """
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
