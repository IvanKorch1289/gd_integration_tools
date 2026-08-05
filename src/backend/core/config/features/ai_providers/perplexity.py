"""Cycle 35 — PerplexitySettings (thin pydantic-settings wrapper).

Perplexity AI — search + chat. Endpoint: ``https://api.perplexity.ai``.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class PerplexitySettings(BaseSettings):
    """Perplexity AI — lightweight pydantic-settings.

    Env-var prefix: ``PERPLEXITY_``.
    Extra env-vars silently ignored (``extra="ignore"``).
    """

    model_config = SettingsConfigDict(env_prefix="PERPLEXITY_", extra="ignore")

    api_key: SecretStr = SecretStr("")
    base_url: str = "https://api.perplexity.ai"
    timeout: int = 30
    scope: str = "default"


__all__ = ("PerplexitySettings",)
