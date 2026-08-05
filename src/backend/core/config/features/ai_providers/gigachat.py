"""Cycle 35 — GigaChatSettings (thin pydantic-settings wrapper).

GigaChat — российский LLM (Sber). Endpoint:
``https://gigachat.devices.sberbank.ru/api/v1``.

Это lightweight-обёртка для hot-path интеграций: api_key + base_url +
timeout + scope. Полная конфигурация провайдера (model/max_tokens/
temperature и т.п.) — в :mod:`core.config.ai.GigaChatSettings`.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GigaChatSettings(BaseSettings):
    """GigaChat (Sber) — lightweight pydantic-settings.

    Env-var prefix: ``GIGACHAT_``.
    Extra env-vars silently ignored (``extra="ignore"``) для forward-compat
    с будущими полями полного :class:`core.config.ai.GigaChatSettings`.
    """

    model_config = SettingsConfigDict(env_prefix="GIGACHAT_", extra="ignore")

    api_key: SecretStr = SecretStr("")
    base_url: str = "https://gigachat.devices.sberbank.ru/api/v1"
    timeout: int = 30
    scope: str = "default"


__all__ = ("GigaChatSettings",)
