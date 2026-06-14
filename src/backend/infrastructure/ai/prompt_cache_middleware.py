"""S127 W4 + S128 W3 — Prompt Caching для Anthropic и OpenAI (TD-022).

Anthropic prompt caching экономит 50-90% input tokens на повторных
вызовах с идентичным system prompt / tools. Активируется через
``cache_control: {"type": "ephemeral"}`` блок в messages.

OpenAI prompt caching (S128 W3, GPT-4o/o1/o3 серии) — отдельный
механизм: ``prompt_cache_key`` parameter + automatic caching при
повторных вызовах с тем же prefix. Не использует ``cache_control``.

Этот модуль:
1. Определяет, поддерживает ли модель prompt caching (anthropic/* / openai/gpt-4o+).
2. Инжектирует ``cache_control: {"type": "ephemeral"}`` для Anthropic
   в user message content (для LiteLLM path) или system message.
3. Инжектирует ``prompt_cache_key`` в request для OpenAI (через wrapper dict).
4. Ничего не делает для non-cacheable моделей (no-op).

TTL: по умолчанию 5 минут (Anthropic ephemeral cache). Настраивается
через :class:`PromptCacheConfig` в feature flags.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.backend.core.logging import get_logger

__all__ = (
    "PromptCacheConfig",
    "inject_openai_prompt_cache",
    "inject_prompt_cache",
    "is_anthropic_cacheable",
    "is_openai_cacheable",
)

_logger = get_logger("infrastructure.ai.prompt_cache")


@dataclass
class PromptCacheConfig:
    """Настройки prompt caching.

    Attributes:
        enabled: Глобальный enable/disable (default True).
        ttl_seconds: TTL ephemeral cache (default 300 = 5 min,
            Anthropic limit).
        apply_to_user_content: Инжектить cache_control в user content
            (default True — самый простой path).
    """

    enabled: bool = True
    ttl_seconds: int = 300
    apply_to_user_content: bool = True


_DEFAULT_CONFIG = PromptCacheConfig()


def is_anthropic_cacheable(model: str) -> bool:
    """Проверить, поддерживает ли модель Anthropic prompt caching.

    Returns:
        True если ``model.startswith("anthropic/")`` И содержит
        cacheable variant (claude-3-5-sonnet, claude-3-7-sonnet,
        claude-sonnet-4, claude-opus-4 и т.д.).

    Note: ``claude-3-haiku`` и старые модели — НЕ поддерживают
    prompt caching (Anthropic docs, 2024-08).
    """
    if not model or not model.startswith("anthropic/"):
        return False
    model_id = model[len("anthropic/"):]
    # Strip date suffix (e.g., "claude-3-5-sonnet-20241022" → "claude-3-5-sonnet").
    base = model_id.split("-")[0:4]
    base_id = "-".join(base)
    cacheable_prefixes = (
        "claude-3-5-sonnet",
        "claude-3-5-haiku",  # haiku 3.5 DOES support caching
        "claude-3-7-sonnet",
        "claude-sonnet-4",
        "claude-opus-4",
        "claude-haiku-4",
    )
    return any(base_id.startswith(prefix) for prefix in cacheable_prefixes)


def is_openai_cacheable(model: str) -> bool:
    """Проверить, поддерживает ли OpenAI модель prompt caching.

    OpenAI prompt caching (2024-11+) поддерживается для:
    - gpt-4o, gpt-4o-mini, gpt-4o-2024-08-06+
    - gpt-4-turbo, gpt-4-turbo-2024-04-09+
    - o1, o1-mini, o1-preview
    - o3-mini

    НЕ поддерживается:
    - gpt-3.5-turbo (все версии)
    - gpt-4 (legacy, 0613/0314/etc) — НЕ turbo, НЕ o

    Returns:
        True если ``model.startswith("openai/")`` И содержит cacheable variant.
    """
    if not model or not model.startswith("openai/"):
        return False
    model_id = model[len("openai/"):].lower()
    # Positive cacheable check first (gpt-4-turbo / gpt-4o / o1 / o3)
    cacheable_prefixes = (
        "gpt-4o",
        "gpt-4-turbo",
        "o1",
        "o3",
    )
    if not any(model_id.startswith(p) for p in cacheable_prefixes):
        return False
    # gpt-3.5-turbo: never cacheable
    if model_id.startswith("gpt-3.5"):
        return False
    return True


def inject_prompt_cache(
    messages: list[dict[str, Any]],
    model: str,
    config: PromptCacheConfig | None = None,
) -> list[dict[str, Any]]:
    """Инжектировать ``cache_control: {"type": "ephemeral"}`` в messages.

    Args:
        messages: LiteLLM-style messages list.
        model: Model name (e.g., ``"anthropic/claude-3-5-sonnet-20241022"``).
        config: Optional config (default: ``PromptCacheConfig()`` with 5min TTL).

    Returns:
        Новый messages list с cache_control injection (или original
        если model не cacheable или config disabled).
    """
    cfg = config or _DEFAULT_CONFIG
    if not cfg.enabled:
        return messages
    if not is_anthropic_cacheable(model):
        return messages

    cache_control = {"type": "ephemeral", "ttl": cfg.ttl_seconds}
    new_messages: list[dict[str, Any]] = []

    for msg in messages:
        new_msg = dict(msg)
        content = msg.get("content")

        # Inject cache_control в user message (litellm path).
        if (
            cfg.apply_to_user_content
            and msg.get("role") == "user"
            and isinstance(content, str)
        ):
            new_msg["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": cache_control,
                }
            ]
        # Inject cache_control в system message (если role=system).
        elif (
            msg.get("role") == "system"
            and isinstance(content, str)
        ):
            new_msg["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": cache_control,
                }
            ]
        # Если content уже list (multi-block) — добавляем cache_control
        # к последнему блоку.
        elif isinstance(content, list) and content:
            new_content = list(content)
            last_block = dict(new_content[-1])
            last_block["cache_control"] = cache_control
            new_content[-1] = last_block
            new_msg["content"] = new_content

        new_messages.append(new_msg)

    _logger.debug(
        "Prompt cache injected for model=%s (messages=%d, ttl=%ds)",
        model,
        len(new_messages),
        cfg.ttl_seconds,
    )
    return new_messages


def _derive_openai_cache_key(messages: list[dict[str, Any]]) -> str:
    """Генерирует стабильный cache key из system + first user message.

    OpenAI ``prompt_cache_key`` принимает строку 1-64 chars. Берём хэш
    от первых 2 сообщений (system + user) — это и есть стабильный
    prefix, по которому OpenAI матчит кэш.
    """
    import hashlib

    parts: list[str] = []
    for msg in messages[:2]:
        content = msg.get("content", "")
        if isinstance(content, list):
            content = str(content)
        elif not isinstance(content, str):
            content = str(content)
        parts.append(f"{msg.get('role')}:{content[:200]}")
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"cache_{digest[:32]}"


def inject_openai_prompt_cache(
    messages: list[dict[str, Any]],
    model: str,
    config: PromptCacheConfig | None = None,
) -> dict[str, Any]:
    """Инжектировать ``prompt_cache_key`` для OpenAI prompt caching.

    Args:
        messages: LiteLLM-style messages list.
        model: Model name (e.g., ``"openai/gpt-4o-mini"``).
        config: Optional config (default: ``PromptCacheConfig()``).

    Returns:
        Dict с kwargs для merge в LiteLLM ``acompletion`` call:
        ``{"prompt_cache_key": "...", "prompt_cache_retention": "in-memory"}``.
        Empty dict если model не cacheable или config disabled.
    """
    cfg = config or _DEFAULT_CONFIG
    if not cfg.enabled:
        return {}
    if not is_openai_cacheable(model):
        return {}

    cache_key = _derive_openai_cache_key(messages)
    _logger.debug(
        "OpenAI prompt cache key derived for model=%s (key=%s, messages=%d)",
        model,
        cache_key,
        len(messages),
    )
    return {
        "prompt_cache_key": cache_key,
        "prompt_cache_retention": "in-memory",
    }
