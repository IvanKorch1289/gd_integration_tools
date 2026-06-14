"""S127 W4 — Prompt Caching for Anthropic (TD-022 partial).

Anthropic prompt caching экономит 50-90% input tokens на повторных
вызовах с идентичным system prompt / tools. Активируется через
``cache_control: {"type": "ephemeral"}`` блок в messages.

Этот модуль:
1. Определяет, поддерживает ли модель prompt caching (anthropic/*).
2. Инжектирует ``cache_control: {"type": "ephemeral"}`` в user message
   content (для LiteLLM path) или system message (если выделен).
3. Ничего не делает для non-anthropic моделей (no-op).

TTL: по умолчанию 5 минут (Anthropic ephemeral cache). Настраивается
через :class:`PromptCacheConfig` в feature flags.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.backend.core.logging import get_logger

__all__ = (
    "PromptCacheConfig",
    "inject_prompt_cache",
    "is_anthropic_cacheable",
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
