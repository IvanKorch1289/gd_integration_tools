"""Переиспользуемые Pydantic-миксины для Settings-классов.

Миксины — обычные ``BaseModel`` (не ``BaseSettings``). Примешиваются к
конкретным Settings через multiple inheritance, чтобы убрать дублирование
полей подключения, retry-политик и LLM-параметров:

    class MySettings(ConnectionMixin, RetryMixin, BaseSettingsWithLoader):
        model_config = SettingsConfigDict(env_prefix="MY_")

Поля миксина наследуются как обычные аннотации; ``BaseSettings`` добавляет
``env_prefix`` и чтение из ENV/YAML поверх них.

Defaults взяты из существующих файлов (``core/config/ai.py``,
``core/config/database.py``, ``core/config/http_base.py``).
"""

from pydantic import BaseModel, Field, SecretStr

__all__ = ("ConnectionMixin", "RetryMixin", "LLMModelMixin")


class ConnectionMixin(BaseModel):
    """Сетевые параметры подключения: host/port/base_url, таймауты, креды.

    Покрывает топ-дубликаты: ``host``, ``port``, ``base_url``,
    ``connect_timeout``, ``read_timeout``, ``username``, ``password``,
    ``api_key``, ``ca_bundle``.
    """

    host: str = Field(
        default="",
        max_length=253,
        description="Хост сервера (IP или доменное имя).",
        examples=["db.example.com"],
    )

    port: int = Field(
        default=0,
        ge=0,
        lt=65536,
        description="Порт для подключения.",
        examples=[5432],
    )

    base_url: str = Field(
        default="",
        description="Базовый URL API/сервиса.",
        examples=["https://api.example.com"],
    )

    connect_timeout: float = Field(
        default=10.0,
        ge=1.0,
        description="Таймаут установки соединения (сек).",
        examples=[10.0],
    )

    read_timeout: float = Field(
        default=60.0,
        ge=1.0,
        description="Таймаут чтения ответа (сек).",
        examples=[60.0],
    )

    username: str = Field(
        default="",
        description="Имя пользователя для аутентификации.",
        examples=["app_user"],
    )

    password: SecretStr = Field(
        default=SecretStr(""),
        description="Пароль (хранится как SecretStr).",
    )

    api_key: SecretStr = Field(
        default=SecretStr(""),
        description="API-ключ сервиса (хранится как SecretStr).",
    )

    ca_bundle: str | None = Field(
        default=None,
        description="Путь к CA-бандлу для TLS-верификации.",
        examples=["/etc/ssl/certs/ca-bundle.crt"],
    )


class RetryMixin(BaseModel):
    """Политика повторов и circuit breaker.

    Покрывает топ-дубликаты: ``max_retries``, ``retry_delay``,
    ``circuit_breaker_max_failures``, ``circuit_breaker_reset_timeout``.
    """

    max_retries: int = Field(
        default=3,
        ge=0,
        description="Максимальное число повторных попыток.",
        examples=[3],
    )

    retry_delay: float = Field(
        default=0.5,
        ge=0.0,
        description="Базовая задержка между повторами (сек, экспоненциальный backoff).",
        examples=[0.5],
    )

    circuit_breaker_max_failures: int = Field(
        default=5,
        ge=0,
        description="Число неудач до размыкания circuit breaker.",
        examples=[5],
    )

    circuit_breaker_reset_timeout: float = Field(
        default=60.0,
        ge=0.0,
        description="Таймаут сброса circuit breaker (сек).",
        examples=[60.0],
    )


class LLMModelMixin(BaseModel):
    """Параметры LLM-модели.

    Покрывает повторяющиеся тройку ``model``, ``max_tokens``, ``temperature``
    из AI-провайдеров (Perplexity, OpenAI, HuggingFace, OpenRouter, NIM, MiniMax).
    """

    model: str = Field(
        default="gpt-4o-mini",
        description="Имя/slug модели у провайдера.",
        examples=["gpt-4o-mini", "sonar", "llama3"],
    )

    max_tokens: int = Field(
        default=4096,
        ge=1,
        le=131072,
        description="Максимальное число токенов в ответе.",
    )

    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Температура генерации (0 — детерминированно, 2 — креативно).",
    )
