"""Настройки AI-провайдеров: Perplexity, HuggingFace, OpenWebUI.

Три уровня AI-провайдеров по приоритету:
1. Perplexity — основной (поиск + chat через WAF)
2. HuggingFace — fallback (Inference API)
3. OpenWebUI — внутренний сервер (полный контроль)
"""

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader

__all__ = (
    "PerplexitySettings",
    "HuggingFaceSettings",
    "OpenWebUISettings",
    "AIProvidersSettings",
    "ai_providers_settings",
)


class PerplexitySettings(BaseSettingsWithLoader):
    """Perplexity AI — основной провайдер для поиска и чата."""

    yaml_group: ClassVar[str] = "perplexity"
    model_config = SettingsConfigDict(env_prefix="PERPLEXITY_", extra="forbid")

    api_key: str = Field(default="", description="API-ключ Perplexity")

    model: str = Field(
        default="sonar",
        description="Модель по умолчанию (sonar, sonar-pro, sonar-reasoning)",
        examples=["sonar", "sonar-pro"],
    )

    base_url: str = Field(
        default="https://api.perplexity.ai", description="Базовый URL API"
    )

    use_waf: bool = Field(default=True, description="Проксировать запросы через WAF")

    max_tokens: int = Field(
        default=4096, ge=1, le=32768, description="Максимальное число токенов в ответе"
    )

    temperature: float = Field(
        default=0.7, ge=0.0, le=2.0, description="Температура генерации"
    )


class HuggingFaceSettings(BaseSettingsWithLoader):
    """HuggingFace Inference API — fallback-провайдер."""

    yaml_group: ClassVar[str] = "huggingface"
    model_config = SettingsConfigDict(env_prefix="HUGGINGFACE_", extra="forbid")

    api_key: str = Field(default="", description="HuggingFace API токен")

    model: str = Field(
        default="mistralai/Mixtral-8x7B-Instruct-v0.1",
        description="Модель на HuggingFace Hub",
    )

    base_url: str = Field(
        default="https://api-inference.huggingface.co/models",
        description="Базовый URL Inference API",
    )

    use_waf: bool = Field(
        default=True,
        description="Проксировать запросы через корпоративный WAF (внешний сервис)",
    )

    max_tokens: int = Field(
        default=2048, ge=1, le=16384, description="Максимальное число токенов"
    )

    temperature: float = Field(
        default=0.7, ge=0.0, le=2.0, description="Температура генерации"
    )


class OpenWebUISettings(BaseSettingsWithLoader):
    """OpenWebUI — внутренний сервер с LLM (полный контроль)."""

    yaml_group: ClassVar[str] = "open_webui"
    model_config = SettingsConfigDict(env_prefix="OPEN_WEBUI_", extra="forbid")

    api_key: str = Field(default="", description="API-ключ OpenWebUI")

    model: str = Field(
        default="llama3",
        description="Модель на внутреннем сервере",
        examples=["llama3", "mistral", "qwen2"],
    )

    base_url: str = Field(
        default="http://localhost:3000", description="URL внутреннего OpenWebUI сервера"
    )

    use_waf: bool = Field(
        default=False,
        description=(
            "Проксировать через WAF (false по-умолчанию: OpenWebUI во "
            "внутреннем контуре, WAF не требуется)."
        ),
    )

    max_tokens: int = Field(
        default=4096, ge=1, le=32768, description="Максимальное число токенов"
    )

    temperature: float = Field(
        default=0.7, ge=0.0, le=2.0, description="Температура генерации"
    )


class AIProvidersSettings(BaseSettingsWithLoader):
    """Агрегированные настройки AI-провайдеров.

    Определяет порядок приоритета и общие параметры
    для маскировки данных перед отправкой в LLM.
    """

    yaml_group: ClassVar[str] = "ai_providers"
    model_config = SettingsConfigDict(env_prefix="AI_", extra="forbid")

    default_provider: str = Field(
        default="perplexity",
        description="Провайдер по умолчанию (perplexity, huggingface, open_webui)",
    )

    fallback_chain: list[str] = Field(
        default=["perplexity", "huggingface", "open_webui"],
        description="Порядок fallback при недоступности провайдера",
    )

    enable_data_sanitization: bool = Field(
        default=True, description="Маскировать PII перед отправкой в LLM"
    )

    sanitize_emails: bool = Field(default=True)
    sanitize_phones: bool = Field(default=True)
    sanitize_inn: bool = Field(default=True)
    sanitize_snils: bool = Field(default=True)
    sanitize_passport: bool = Field(default=True)
    sanitize_card_numbers: bool = Field(default=True)
    sanitize_api_keys: bool = Field(default=True)

    custom_sensitive_fields: list[str] = Field(
        default_factory=list, description="Дополнительные поля для маскировки"
    )

    connect_timeout: float = Field(
        default=10.0, ge=1.0, description="Таймаут подключения к AI API (сек)"
    )

    read_timeout: float = Field(
        default=60.0, ge=1.0, description="Таймаут чтения ответа от AI API (сек)"
    )


ai_providers_settings = AIProvidersSettings()
