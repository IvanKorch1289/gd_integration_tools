"""Cycle 35 — regression tests для 4 AI-провайдеров settings (N2 task).

Покрывает по 1 тесту на провайдера:
    - GigaChatSettings: defaults + env-override + SecretStr-redaction + base_url default;
    - TavilySettings: defaults + env-override + SecretStr-redaction + base_url default;
    - PerplexitySettings: defaults + env-override + SecretStr-redaction + base_url default;
    - NimSettings: defaults + env-override + SecretStr-redaction + base_url default.

Каждый тест проверяет 4 инварианта:
    1. default values (timeout=30, scope="default");
    2. env-override (api_key/base_url/timeout через env_prefix);
    3. SecretStr redaction (repr не содержит raw secret);
    4. base_url default (per-provider endpoint).
"""

from __future__ import annotations

import os

from src.backend.core.config.features.ai_providers import (
    GigaChatSettings,
    NimSettings,
    PerplexitySettings,
    TavilySettings,
)


class TestGigaChatSettings:
    """GigaChat (Sber)."""

    ENV_PREFIX = "GIGACHAT_"
    ENV_KEY = "GIGACHAT_API_KEY"
    SECRET = "gigachat-secret-12345"
    EXPECTED_DEFAULT_BASE_URL = "https://gigachat.devices.sberbank.ru/api/v1"

    def test_defaults(self) -> None:
        # Сбрасываем env чтобы не утекал параллельный test
        for var in (self.ENV_KEY, "GIGACHAT_BASE_URL", "GIGACHAT_TIMEOUT", "GIGACHAT_SCOPE"):
            os.environ.pop(var, None)
        s = GigaChatSettings()
        assert s.api_key.get_secret_value() == ""
        assert s.base_url == self.EXPECTED_DEFAULT_BASE_URL
        assert s.timeout == 30
        assert s.scope == "default"

    def test_env_override(self) -> None:
        os.environ[self.ENV_KEY] = self.SECRET
        os.environ["GIGACHAT_BASE_URL"] = "https://gigachat-proxy.local/api/v1"
        os.environ["GIGACHAT_TIMEOUT"] = "60"
        os.environ["GIGACHAT_SCOPE"] = "GIGACHAT_API_CORP"
        try:
            s = GigaChatSettings()
            assert s.api_key.get_secret_value() == self.SECRET
            assert s.base_url == "https://gigachat-proxy.local/api/v1"
            assert s.timeout == 60
            assert s.scope == "GIGACHAT_API_CORP"
        finally:
            for var in (self.ENV_KEY, "GIGACHAT_BASE_URL", "GIGACHAT_TIMEOUT", "GIGACHAT_SCOPE"):
                os.environ.pop(var, None)

    def test_secret_str_redaction(self) -> None:
        os.environ[self.ENV_KEY] = self.SECRET
        try:
            s = GigaChatSettings()
            # repr() должен маскировать секрет (SecretStr.__repr__ → SecretStr('**********'))
            assert self.SECRET not in repr(s)
            assert self.SECRET not in str(s)
            # но get_secret_value() возвращает raw
            assert s.api_key.get_secret_value() == self.SECRET
        finally:
            os.environ.pop(self.ENV_KEY, None)

    def test_base_url_default(self) -> None:
        os.environ.pop("GIGACHAT_BASE_URL", None)
        s = GigaChatSettings()
        assert s.base_url == self.EXPECTED_DEFAULT_BASE_URL


class TestTavilySettings:
    """Tavily (search API)."""

    ENV_PREFIX = "TAVILY_"
    ENV_KEY = "TAVILY_API_KEY"
    SECRET = "tvly-secret-67890"
    EXPECTED_DEFAULT_BASE_URL = "https://api.tavily.com"

    def test_defaults(self) -> None:
        for var in (self.ENV_KEY, "TAVILY_BASE_URL", "TAVILY_TIMEOUT", "TAVILY_SCOPE"):
            os.environ.pop(var, None)
        s = TavilySettings()
        assert s.api_key.get_secret_value() == ""
        assert s.base_url == self.EXPECTED_DEFAULT_BASE_URL
        assert s.timeout == 30
        assert s.scope == "default"

    def test_env_override(self) -> None:
        os.environ[self.ENV_KEY] = self.SECRET
        os.environ["TAVILY_BASE_URL"] = "https://tavily-proxy.local"
        os.environ["TAVILY_TIMEOUT"] = "45"
        os.environ["TAVILY_SCOPE"] = "advanced"
        try:
            s = TavilySettings()
            assert s.api_key.get_secret_value() == self.SECRET
            assert s.base_url == "https://tavily-proxy.local"
            assert s.timeout == 45
            assert s.scope == "advanced"
        finally:
            for var in (self.ENV_KEY, "TAVILY_BASE_URL", "TAVILY_TIMEOUT", "TAVILY_SCOPE"):
                os.environ.pop(var, None)

    def test_secret_str_redaction(self) -> None:
        os.environ[self.ENV_KEY] = self.SECRET
        try:
            s = TavilySettings()
            assert self.SECRET not in repr(s)
            assert self.SECRET not in str(s)
            assert s.api_key.get_secret_value() == self.SECRET
        finally:
            os.environ.pop(self.ENV_KEY, None)

    def test_base_url_default(self) -> None:
        os.environ.pop("TAVILY_BASE_URL", None)
        s = TavilySettings()
        assert s.base_url == self.EXPECTED_DEFAULT_BASE_URL


class TestPerplexitySettings:
    """Perplexity AI (search + chat)."""

    ENV_PREFIX = "PERPLEXITY_"
    ENV_KEY = "PERPLEXITY_API_KEY"
    SECRET = "pplx-secret-abcde"
    EXPECTED_DEFAULT_BASE_URL = "https://api.perplexity.ai"

    def test_defaults(self) -> None:
        for var in (self.ENV_KEY, "PERPLEXITY_BASE_URL", "PERPLEXITY_TIMEOUT", "PERPLEXITY_SCOPE"):
            os.environ.pop(var, None)
        s = PerplexitySettings()
        assert s.api_key.get_secret_value() == ""
        assert s.base_url == self.EXPECTED_DEFAULT_BASE_URL
        assert s.timeout == 30
        assert s.scope == "default"

    def test_env_override(self) -> None:
        os.environ[self.ENV_KEY] = self.SECRET
        os.environ["PERPLEXITY_BASE_URL"] = "https://perplexity-proxy.local"
        os.environ["PERPLEXITY_TIMEOUT"] = "90"
        os.environ["PERPLEXITY_SCOPE"] = "deep"
        try:
            s = PerplexitySettings()
            assert s.api_key.get_secret_value() == self.SECRET
            assert s.base_url == "https://perplexity-proxy.local"
            assert s.timeout == 90
            assert s.scope == "deep"
        finally:
            for var in (self.ENV_KEY, "PERPLEXITY_BASE_URL", "PERPLEXITY_TIMEOUT", "PERPLEXITY_SCOPE"):
                os.environ.pop(var, None)

    def test_secret_str_redaction(self) -> None:
        os.environ[self.ENV_KEY] = self.SECRET
        try:
            s = PerplexitySettings()
            assert self.SECRET not in repr(s)
            assert self.SECRET not in str(s)
            assert s.api_key.get_secret_value() == self.SECRET
        finally:
            os.environ.pop(self.ENV_KEY, None)

    def test_base_url_default(self) -> None:
        os.environ.pop("PERPLEXITY_BASE_URL", None)
        s = PerplexitySettings()
        assert s.base_url == self.EXPECTED_DEFAULT_BASE_URL


class TestNimSettings:
    """Nvidia NIM (OpenAI-compatible)."""

    ENV_PREFIX = "NIM_"
    ENV_KEY = "NIM_API_KEY"
    SECRET = "nvapi-secret-fghij"
    EXPECTED_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"

    def test_defaults(self) -> None:
        for var in (self.ENV_KEY, "NIM_BASE_URL", "NIM_TIMEOUT", "NIM_SCOPE"):
            os.environ.pop(var, None)
        s = NimSettings()
        assert s.api_key.get_secret_value() == ""
        assert s.base_url == self.EXPECTED_DEFAULT_BASE_URL
        assert s.timeout == 30
        assert s.scope == "default"

    def test_env_override(self) -> None:
        os.environ[self.ENV_KEY] = self.SECRET
        os.environ["NIM_BASE_URL"] = "https://nim-selfhosted.local/v1"
        os.environ["NIM_TIMEOUT"] = "120"
        os.environ["NIM_SCOPE"] = "embed"
        try:
            s = NimSettings()
            assert s.api_key.get_secret_value() == self.SECRET
            assert s.base_url == "https://nim-selfhosted.local/v1"
            assert s.timeout == 120
            assert s.scope == "embed"
        finally:
            for var in (self.ENV_KEY, "NIM_BASE_URL", "NIM_TIMEOUT", "NIM_SCOPE"):
                os.environ.pop(var, None)

    def test_secret_str_redaction(self) -> None:
        os.environ[self.ENV_KEY] = self.SECRET
        try:
            s = NimSettings()
            assert self.SECRET not in repr(s)
            assert self.SECRET not in str(s)
            assert s.api_key.get_secret_value() == self.SECRET
        finally:
            os.environ.pop(self.ENV_KEY, None)

    def test_base_url_default(self) -> None:
        os.environ.pop("NIM_BASE_URL", None)
        s = NimSettings()
        assert s.base_url == self.EXPECTED_DEFAULT_BASE_URL
