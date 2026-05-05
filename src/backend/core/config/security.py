import os
from typing import ClassVar, Literal

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("SecureSettings", "secure_settings")


class SecureSettings(BaseSettingsWithLoader):
    """Конфигурация системы аутентификации и авторизации.

    Содержит параметры безопасности для работы с токенами, API-ключами,
    настройками Cookie и механизмами защиты от атак.
    """

    yaml_group: ClassVar[str] = "security"
    model_config = SettingsConfigDict(env_prefix="SEC_", extra="forbid")

    # Основные настройки токенов
    token_lifetime: int = Field(
        ...,
        ge=60,
        description="Время жизни токена в секундах (минимум 60)",
        examples=[3600, 86400],
    )
    refresh_token_lifetime: int = Field(
        ...,
        ge=3600,
        description="Время жизни refresh-токена в секундах (по умолчанию 30 дней)",
        examples=[2592000, 86400],
    )

    # Алгоритмы и криптография
    secret_key: str = Field(
        ...,
        min_length=32,
        description="Секретный ключ для подписи токенов (минимум 32 символа)",
        examples=["supersecretkeywithatleast32characters123"],
    )
    algorithm: Literal["HS256", "HS384", "HS512", "RS256"] = Field(
        ..., description="Алгоритм подписи токенов", examples=["HS256", "RS256"]
    )

    # API-безопасность
    api_key: str = Field(
        ..., description="Основной API-ключ приложения", examples=["your_api_key_123"]
    )
    allowed_hosts: list[str] = Field(
        ...,
        description="Разрешенные хосты для входящих запросов",
        examples=["example.com", "api.example.com"],
    )
    cors_origins: list[str] = Field(
        default_factory=list,
        description=(
            "CORS allow-origins whitelist. В prod-окружении запрещён '*' — "
            "список должен быть явным."
        ),
        examples=[["https://app.example.com", "https://admin.example.com"]],
    )
    cors_allow_credentials: bool = Field(
        default=True,
        description="Разрешить отправку cookies/auth headers в cross-origin запросах",
    )
    cors_allow_methods: list[str] = Field(
        default_factory=lambda: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        description="Разрешённые HTTP-методы для cross-origin",
    )
    cors_allow_headers: list[str] = Field(
        default_factory=lambda: [
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "X-API-Key",
        ],
        description="Разрешённые заголовки для cross-origin",
    )

    @field_validator("cors_origins")
    @classmethod
    def _forbid_wildcard_in_prod(cls, value: list[str]) -> list[str]:
        """В prod-окружении запрещён '*' — требуется явный whitelist."""
        env = os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "dev"
        if env.lower() in {"prod", "production"} and "*" in value:
            raise ValueError(
                "CORS wildcard '*' запрещён в prod. Укажите явный список origin."
            )
        return value

    routes_without_api_key: list[str] = Field(
        ...,
        description="Эндпоинты, доступные без API-ключа",
        examples=["/health", "/status"],
    )
    admin_ips: set[str] = Field(
        ...,
        description="IP-адреса, из которых разрешен доступ к административным эндпоинтам'",
        examples=["127.0.0.1", "192.168.0.1"],
    )
    admin_routes: set[str] = Field(
        ...,
        description="Эндпоинты, доступные только для администраторов",
        examples=["/admin/users", "/admin/logs"],
    )

    # Защита от атак и лимиты
    request_timeout: float = Field(
        ...,
        description="Максимальное время обработки запроса (секунды)",
        examples=[5.0, 10.0],
    )
    rate_limit: int = Field(
        ..., description="Лимит запросов в минуту для приложения", examples=[100, 500]
    )
    rate_time_measure_seconds: int = Field(
        ...,
        description="Временное окно для ограничения запросов (секунды)",
        examples=[60, 300],
    )


secure_settings = SecureSettings()
"""Глобальные настройки безопасности"""
