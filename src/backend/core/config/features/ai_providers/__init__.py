"""Cycle 35 — pydantic-settings для AI-провайдеров.

Назначение:
    Лёгкие настройки для 4 внешних AI-провайдеров (GigaChat, Tavily,
    Perplexity, Nvidia NIM). Каждый провайдер — отдельный
    ``BaseSettings`` subclass с env_prefix (GIGACHAT_/TAVILY_/
    PERPLEXITY_/NIM_) и ``extra="ignore"`` для forward-compat.

Контракт:
    - ``api_key: SecretStr`` — секрет не сериализуется в repr/log;
    - ``base_url: str`` — override endpoint для self-hosted/прокси;
    - ``timeout: int = 30`` — таймаут HTTP-запроса (сек);
    - ``scope: str = "default"`` — только для GigaChat (OAuth2 scope),
      Tavily/Perplexity/Nim — поле присутствует, но не используется
      upstream (резерв для совместимости с общим интерфейсом).

Использование:
    ``from src.backend.core.config.features.ai_providers import (
        GigaChatSettings, TavilySettings, PerplexitySettings, NimSettings,
    )``

Эти настройки НЕ дублируют :mod:`core.config.ai` (полные настройки
провайдеров со всеми полями) — это thin-wrapper для hot-path интеграций,
где достаточно api_key + base_url + timeout.
"""

from __future__ import annotations

from src.backend.core.config.features.ai_providers.gigachat import GigaChatSettings
from src.backend.core.config.features.ai_providers.nim import NimSettings
from src.backend.core.config.features.ai_providers.perplexity import PerplexitySettings
from src.backend.core.config.features.ai_providers.tavily import TavilySettings

__all__ = (
    "GigaChatSettings",
    "NimSettings",
    "PerplexitySettings",
    "TavilySettings",
)
