from typing import List, Literal

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

from app.config.constants import ROOT_DIR


__all__ = ("AuthSettings",)


# Загрузка переменных окружения из файла .env
load_dotenv(ROOT_DIR / ".env")


class AuthSettings(BaseSettings):
    """Настройки системы аутентификации и авторизации.

    Группы параметров:
    - Основные параметры токена
    - Алгоритмы и ключи
    - Дополнительные настройки
    """

    # Основные параметры токена
    auth_token_name: str = Field(
        default="access_token",
        env="AUTH_TOKEN_NAME",
        description="Имя HTTP-куки/заголовка с токеном",
    )
    auth_token_lifetime: int = Field(
        default=3600,
        ge=60,
        env="AUTH_TOKEN_LIFETIME_SECONDS",
        description="Время жизни токена в секундах (мин. 60)",
    )
    auth_refresh_token_lifetime: int = Field(
        default=2592000,
        ge=3600,
        env="AUTH_REFRESH_TOKEN_LIFETIME_SECONDS",
        description="Время жизни refresh-токена в секундах (по умолчанию 30 дней)",
    )

    # Алгоритмы и ключи
    auth_secret_key: str = Field(
        default="your_secret_key",
        env="AUTH_SECRET_KEY",
        min_length=32,
        description="Секретный ключ для подписи токенов (мин. 32 символа)",
    )
    auth_algorithm: Literal["HS256", "HS384", "HS512", "RS256"] = Field(
        default="HS256",
        env="AUTH_ALGORITHM",
        description="Алгоритм подписи токенов",
    )

    # Дополнительные настройки
    auth_cookie_secure: bool = Field(
        default=False,
        env="AUTH_COOKIE_SECURE",
        description="Передавать токен только по HTTPS",
    )
    auth_cookie_samesite: Literal["lax", "strict", "none"] = Field(
        default="lax",
        env="AUTH_COOKIE_SAMESITE",
        description="Политика SameSite для cookie",
    )

    @field_validator("auth_algorithm")
    @classmethod
    def validate_algorithm(cls, v):
        if v.startswith("HS") and "secret_key" in cls.model_fields:
            if len(cls.auth_secret_key) < 32:
                raise ValueError(
                    "HS алгоритмы требуют ключ минимум 32 символа"
                )
        return v

    # Безопасность
    auth_api_key: str = Field(
        default="2f0-2340f",
        env="AUTH_API_KEY",
        description="Главный API-ключ приложения",
    )
    auth_allowed_hosts: List[str] = Field(
        default=[
            "example.com",
            "*.example.com",
            "localhost",
            "127.0.0.1",
        ],
        description="Разрешенные хосты для входящих запросов",
    )
    auth_routes_without_api_key: List[str] = Field(
        default=[
            "/",
            "/admin",
            "/admin/*",
            "/docs",
            "/documents",
            "/docs/",
            "/documents/",
            "/metrics",
            "/openapi.json",
            "/tech/healthcheck-*",
            "/tech/redirect-*",
            "/tech/version",
            "/tech/log-storage",
            "/tech/file-storage",
            "/tech/task-monitor",
        ],
        description="Эндпоинты с доступом без API-ключа приложения",
    )
    auth_request_timeout: float = Field(
        default=5.0,
        env="AUTH_REQUEST_TIMEOUT",
        description="Максимальное время ожидания запроса (в секундах)",
    )
    auth_rate_limit: int = Field(
        default=100,
        env="APP_RATE_LIMIT",
        description="Количество запросов в минуту, которое разрешено приложению",
    )
    auth_rate_time_measure_seconds: int = Field(
        default=60,
        env="AUTH_RATE_TIME_MEASURE_SECONDS",
        description="Время измерения посещений (в секундах)",
    )
