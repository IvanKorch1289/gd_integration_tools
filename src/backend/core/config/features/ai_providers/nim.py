"""Cycle 35 — NimSettings (thin pydantic-settings wrapper).

Nvidia NIM — OpenAI-compatible LLM microservices. Endpoint:
``https://integrate.api.nvidia.com/v1``.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class NimSettings(BaseSettings):
    """Nvidia NIM — lightweight pydantic-settings.

    Env-var prefix: ``NIM_``.
    Extra env-vars silently ignored (``extra="ignore"``).
    """

    model_config = SettingsConfigDict(env_prefix="NIM_", extra="ignore")

    api_key: SecretStr = SecretStr("")
    base_url: str = "https://integrate.api.nvidia.com/v1"
    timeout: int = 30
    scope: str = "default"


__all__ = ("NimSettings",)
