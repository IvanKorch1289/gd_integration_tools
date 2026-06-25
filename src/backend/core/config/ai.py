"""Настройки AI-провайдеров.

Стандартный набор провайдеров по приоритету:
1. Perplexity — поиск + chat через WAF.
2. HuggingFace — Inference API (fallback).
3. OpenWebUI — внутренний сервер (полный контроль).
4. OpenRouter — агрегатор моделей по OpenAI-совместимому API.
5. Nvidia NIM — OpenAI-совместимые микросервисы NVIDIA (build.nvidia.com).
6. OpenAI — Assistants API / OpenAI-совместимые прокси (vLLM, LiteLLM, Ollama).
7. MiniMax M-series — китайская LLM (minimax-m2, minimax-m2.5), OpenAI-compatible API.
"""

from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = (
    "AIProvidersSettings",
    "AIWorkspaceSettings",
    "HuggingFaceSettings",
    "MarkitdownSettings",
    "NimSettings",
    "OpenAISettings",
    "MiniMaxSettings",
    "OpenRouterSettings",
    "OpenWebUISettings",
    "PerplexitySettings",
    "ai_providers_settings",
    "ai_workspace_settings",
    "markitdown_settings",
    "minimax_settings",
    "nim_settings",
    "openai_settings",
    "openrouter_settings",
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


class OpenRouterSettings(BaseSettingsWithLoader):
    """OpenRouter — агрегатор LLM-моделей по OpenAI-совместимому API."""

    yaml_group: ClassVar[str] = "openrouter"
    model_config = SettingsConfigDict(env_prefix="OPENROUTER_", extra="forbid")

    api_key: str = Field(default="", description="API-ключ OpenRouter")
    model: str = Field(
        default="openrouter/auto",
        description="Slug модели (см. https://openrouter.ai/models).",
    )
    base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        description="Базовый URL OpenAI-совместимого API.",
    )
    use_waf: bool = Field(default=True, description="Проксировать через WAF.")
    max_tokens: int = Field(default=4096, ge=1, le=131072)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class NimSettings(BaseSettingsWithLoader):
    """Nvidia NIM — OpenAI-совместимые микросервисы NVIDIA."""

    yaml_group: ClassVar[str] = "nim"
    model_config = SettingsConfigDict(env_prefix="NIM_", extra="forbid")

    api_key: str = Field(default="", description="API-ключ build.nvidia.com")
    model: str = Field(
        default="meta/llama-3.1-70b-instruct", description="Слаг модели в каталоге NIM."
    )
    base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        description=(
            "OpenAI-совместимый endpoint. Для self-hosted NIM-инстанса "
            "переопределить URL в overlay профиля."
        ),
    )
    use_waf: bool = Field(default=True)
    max_tokens: int = Field(default=4096, ge=1, le=131072)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class OpenAISettings(BaseSettingsWithLoader):
    """OpenAI / OpenAI-совместимые провайдеры (vLLM, LiteLLM, Ollama)."""

    yaml_group: ClassVar[str] = "openai"
    model_config = SettingsConfigDict(env_prefix="OPENAI_", extra="forbid")

    api_key: str = Field(default="", description="API-ключ провайдера.")
    model: str = Field(
        default="gpt-4o-mini", description="Имя/slug модели у выбранного провайдера."
    )
    base_url: str = Field(
        default="https://api.openai.com/v1",
        description=(
            "Базовый URL OpenAI-совместимого API. Подставьте URL прокси "
            "(vLLM/LiteLLM/Ollama), чтобы переключить провайдера без "
            "изменений кода."
        ),
    )
    use_waf: bool = Field(default=False)
    max_tokens: int = Field(default=4096, ge=1, le=131072)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class MiniMaxSettings(BaseSettingsWithLoader):
    """MiniMax M-series — китайская LLM-платформа с M2/M2.5 моделями.

    OpenAI-совместимый API. Endpoint: https://api.minimax.chat/v1
    Используется для русскоязычных задач, генерации кода и RAG.
    """

    yaml_group: ClassVar[str] = "minimax"
    model_config = SettingsConfigDict(env_prefix="MINIMAX_", extra="forbid")

    api_key: str = Field(default="", description="MiniMax API-ключ")
    model: str = Field(
        default="MiniMax-Text-01",
        description="Слаг модели (MiniMax-Text-01, minimax-m2, minimax-m2.5, etc).",
    )
    base_url: str = Field(
        default="https://api.minimax.chat/v1",
        description="Base URL для MiniMax OpenAI-compatible API.",
    )
    timeout: float = Field(
        default=30.0, ge=1.0, description="Таймаут запроса к MiniMax API (сек)"
    )
    max_retries: int = Field(default=3, ge=0, description="Количество retry при ошибках")



class AIProvidersSettings(BaseSettingsWithLoader):
    """Агрегированные настройки AI-провайдеров.

    Определяет порядок приоритета и общие параметры
    для маскировки данных перед отправкой в LLM.
    """

    yaml_group: ClassVar[str] = "ai_providers"
    model_config = SettingsConfigDict(env_prefix="AI_", extra="forbid")

    default_provider: str = Field(
        default="perplexity",
        description=(
            "Провайдер по умолчанию (perplexity, huggingface, open_webui, "
            "openrouter, nim, openai, minimax)."
        ),
    )

    fallback_chain: list[str] = Field(
        default=[
            "perplexity",
            "huggingface",
            "open_webui",
            "openrouter",
            "nim",
            "openai",
            "minimax",
        ],
        description="Порядок fallback при недоступности провайдера.",
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

    search_timeout: float = Field(
        default=30.0, ge=1.0, description="Таймаут поискового запроса (сек)"
    )

    search_deep_timeout: float = Field(
        default=60.0, ge=1.0, description="Таймаут deep-research запроса (сек)"
    )


class AIWorkspaceSettings(BaseSettingsWithLoader):
    """Настройки изолированного AI-workspace (V15 R-V15-4, Wave 1.6).

    AI-плагины пишут только в ``${workspace_root}/<tenant>/<session>/``;
    cleanup-loop удаляет TTL-expired sessions с указанным интервалом.
    Per-tenant квота — суммарный размер живых sessions.
    """

    yaml_group: ClassVar[str] = "ai_workspace"
    model_config = SettingsConfigDict(env_prefix="AI_WORKSPACE_", extra="ignore")

    workspace_root: Path = Field(
        default=Path("./var/ai_workspace"),
        description="Корневой каталог AI-workspace (TTL-expirable sessions).",
    )

    workspace_ttl_seconds: float = Field(
        default=7 * 24 * 3600,
        ge=60.0,
        description="TTL отдельной session-папки (по умолчанию 7 дней).",
    )

    workspace_quota_bytes: int = Field(
        default=500 * 1024 * 1024,
        ge=1024,
        description="Per-tenant квота на сумму размеров живых sessions (байты).",
    )

    workspace_cleanup_interval_s: float = Field(
        default=6 * 3600,
        ge=60.0,
        description="Период cleanup-loop удаления TTL-expired sessions.",
    )


class MarkitdownSettings(BaseSettingsWithLoader):
    """Настройки markitdown-engine для document_parsers (Sprint S5 hotfix).

    Markitdown — Microsoft-овская конвертация PDF/DOCX/PPTX/XLSX/HTML/CSV/JSON
    в Markdown с сохранением структуры (заголовки, таблицы, списки). Включён
    по умолчанию; при провале/недоступности — fallback на legacy pypdf/docx
    извлечение plain-text.

    Сетевые fetcher'ы markitdown (resolve URL внутри документа) проходят
    через WAF (V15 R-V15-5) только при ``network_mode='waf'``. По умолчанию
    ``network_mode='off'`` — никаких outbound-вызовов.
    """

    yaml_group: ClassVar[str] = "markitdown"
    model_config = SettingsConfigDict(env_prefix="MARKITDOWN_", extra="ignore")

    engine_enabled: bool = Field(
        default=True,
        description="Использовать markitdown как primary-engine (fallback на legacy).",
    )

    timeout_s: int = Field(
        default=30, ge=1, le=600, description="Таймаут одной конвертации (R-V15-13)."
    )

    max_bytes: int = Field(
        default=25_000_000,
        ge=1024,
        description="Максимальный размер документа для парсинга (байты).",
    )

    network_mode: Literal["off", "waf"] = Field(
        default="off",
        description=(
            "Режим сетевых fetcher'ов markitdown: 'off' — урезаны (default), "
            "'waf' — через OutboundHttpClient + capability net.outbound."
        ),
    )


ai_providers_settings = AIProvidersSettings()
minimax_settings = MiniMaxSettings()
ai_workspace_settings = AIWorkspaceSettings()
markitdown_settings = MarkitdownSettings()
openrouter_settings = OpenRouterSettings()
nim_settings = NimSettings()
openai_settings = OpenAISettings()
