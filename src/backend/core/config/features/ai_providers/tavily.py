"""Cycle 35 — TavilySettings (thin pydantic-settings wrapper).

Tavily — search API для AI-агентов. Endpoint: ``https://api.tavily.com``.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class TavilySettings(BaseSettings):
    """Tavily (search API) — lightweight pydantic-settings.

    Env-var prefix: ``TAVILY_``.
    Extra env-vars silently ignored (``extra="ignore"``).
    """

    model_config = SettingsConfigDict(env_prefix="TAVILY_", extra="ignore")

    api_key: SecretStr = SecretStr("")
    base_url: str = "https://api.tavily.com"
    timeout: int = 30
    scope: str = "default"


__all__ = ("TavilySettings",)
