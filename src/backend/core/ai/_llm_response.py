"""Helpers для разбора litellm-ответов.

Layer 8 Агенты Cycle 1: единая утилита вместо дубликата в
`gateway_pipeline_mixin.llm_mixin._extract_completion` и
`pydantic_ai_client._extract_completion`.
"""

from __future__ import annotations

from typing import Any


def extract_completion(
    response: Any, *, fallback_model: str | None,
) -> tuple[str, int, int, str]:
    """Вытаскивает content/tokens/model из litellm-ответа.

    Поддерживает оба формата:
    * ``litellm.ModelResponse`` — атрибуты ``.choices``, ``.usage``, ``.model``;
    * ``dict`` — те же ключи.

    Args:
        response: litellm ModelResponse ИЛИ dict-эквивалент.
        fallback_model: Модель для подстановки если ``response.model`` пуст.

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
