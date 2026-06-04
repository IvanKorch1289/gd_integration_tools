"""Исключения LiteLLM-шлюза."""

from __future__ import annotations

__all__ = ("GatewayError", "GatewayRateLimited", "GatewayUnavailable")


class GatewayError(RuntimeError):
    """Базовое исключение LiteLLM-шлюза."""


class GatewayUnavailable(GatewayError):
    """Шлюз отключён или библиотека ``litellm`` не установлена."""


class GatewayRateLimited(GatewayError):
    """Провайдер ответил 429 / rate-limit."""
