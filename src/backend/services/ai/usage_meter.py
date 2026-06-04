"""LLM Usage Meter — извлечение токенов из ответа LiteLLM (Sprint 9 K4 W2).

Утилитный модуль для нормализации полей ``usage`` из ответа разных
провайдеров (OpenAI / Anthropic / Mistral). LiteLLM унифицирует
структуру, но иногда поле приходит как dict, иногда как pydantic-объект.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ("UsageStats", "estimate_tokens", "extract_usage")


@dataclass(frozen=True, slots=True)
class UsageStats:
    """Нормализованная статистика usage из LiteLLM-ответа.

    Attributes:
        prompt_tokens: входные токены (запрос).
        completion_tokens: выходные токены (ответ).
        total_tokens: ``prompt + completion``.
    """

    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def extract_usage(response: Any) -> UsageStats:
    """Достать UsageStats из LiteLLM/OpenAI ответа.

    Args:
        response: ответ ``acompletion``. Может быть dict или объект с
            атрибутом ``usage`` (Pydantic / litellm.ModelResponse).

    Returns:
        :class:`UsageStats` с обнулёнными полями если usage не найден.
    """
    usage = (
        response.get("usage")
        if isinstance(response, dict)
        else getattr(response, "usage", None)
    )
    if usage is None:
        return UsageStats(prompt_tokens=0, completion_tokens=0)

    if isinstance(usage, dict):
        prompt = int(usage.get("prompt_tokens", 0) or 0)
        completion = int(usage.get("completion_tokens", 0) or 0)
    else:
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
    return UsageStats(prompt_tokens=prompt, completion_tokens=completion)


def estimate_tokens(messages: list[dict[str, Any]], *, factor: float = 1.3) -> int:
    """Грубая оценка токенов запроса (для pre-call reserve).

    Использует ``len(text) / 4 * factor`` (правило большого пальца для
    английского + 30% запас).

    Args:
        messages: chat-completion messages.
        factor: множитель для запаса (default 1.3).
    """
    total_chars = 0
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for chunk in content:
                if isinstance(chunk, dict) and "text" in chunk:
                    total_chars += len(chunk["text"])
    return max(1, int(total_chars / 4 * factor))
