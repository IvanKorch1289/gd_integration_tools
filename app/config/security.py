from typing import ClassVar, List, Literal, Set

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from app.config.config_loader import BaseSettingsWithLoader


__all__ = (
    "SecureSettings",
    "secure_settings",
)


class SecureSettings(BaseSettingsWithLoader):
    """Конфигурация системы аутентификации и авторизации.

    Содержит параметры безопасности для работы с токенами, API-ключами,
    настройками Cookie и механизмами защиты от атак.
    """

    yaml_group: ClassVar[str] = "security"
    model_config = SettingsConfigDict(
        env_prefix="SEC_",
        extra="forbid",
    )

    # Основные настройки токенов
    token_name: str = Field(
        ...,
        description="Название HTTP-куки/заголовка с токеном",
        examples=["access_token", "auth_token"],
    )
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
        ...,
        description="Алгоритм подписи токенов",
        examples=["HS256", "RS256"],
    )

    # Параметры Cookie
    cookie_secure: bool = Field(
        ...,
        description="Передача токена только по HTTPS",
        examples=[True, False],
    )
    cookie_samesite: Literal["lax", "strict", "none"] = Field(
        ...,
        description="Политика SameSite для Cookie",
        examples=["lax", "strict", "none"],
    )

    # API-безопасность
    api_key: str = Field(
        ...,
        description="Основной API-ключ приложения",
        examples=["your_api_key_123"],
    )
    allowed_hosts: List[str] = Field(
        ...,
        description="Разрешенные хосты для входящих запросов",
        examples=["example.com", "api.example.com"],
    )
    routes_without_api_key: List[str] = Field(
        ...,
        description="Эндпоинты, доступные без API-ключа",
        examples=["/health", "/status"],
    )
    admin_ips: Set[str] = Field(
        ...,
        description="IP-адреса, из которых разрешен доступ к административным эндпоинтам'",
        examples=["127.0.0.1", "192.168.0.1"],
    )
    admin_routes: Set[str] = Field(
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
        ...,
        description="Лимит запросов в минуту для приложения",
        examples=[100, 500],
    )
    rate_time_measure_seconds: int = Field(
        ...,
        description="Временное окно для ограничения запросов (секунды)",
        examples=[60, 300],
    )
    failure_threshold: int = Field(
        ...,
        description="Количество неудачных попыток до блокировки аккаунта",
        examples=[5, 10],
    )
    recovery_timeout: int = Field(
        ...,
        description="Время до разблокировки аккаунта после неудачных попыток (секунды)",
        examples=[600, 3600],
    )


secure_settings = SecureSettings()
"""Глобальные настройки безопасности"""
