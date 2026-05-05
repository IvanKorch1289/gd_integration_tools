"""Агрегатор конфигурации авторизации (Wave 8.1).

Содержит компактные DTO-обёртки поверх существующих ``SecureSettings``
и ``ExpressSettings``, чтобы DSL-процессоры и middleware могли работать
с авторизацией через единый объект, не зная о деталях env-переменных.

Назначение модуля — *доступ к параметрам* JWT/eXpress JWT, а не повторное
объявление настроек. Источник истины — ``settings.secure`` и
``settings.express``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover
    from src.backend.core.config.express import ExpressSettings
    from src.backend.core.config.security import SecureSettings

__all__ = ("JwtConfig", "ExpressJwtConfig", "AuthConfig", "build_auth_config")


class JwtConfig(BaseModel):
    """Конфигурация локального JWT (внутренние сервисные токены)."""

    secret_key: str = Field(..., description="Секретный ключ подписи токена")
    algorithm: str = Field("HS256", description="Алгоритм подписи (HS256/HS512/RS256)")
    token_lifetime: int = Field(
        3600, ge=60, description="Время жизни токена в секундах"
    )


class ExpressJwtConfig(BaseModel):
    """Конфигурация JWT eXpress (BotX issued).

    Используется для верификации токенов, выписанных BotX-сервером:
    audience = ``botx_host``, issuer = ``bot_id``.
    """

    bot_id: str = Field("", description="UUID бота — issuer (iss).")
    secret_key: str = Field("", description="Секрет бота — ключ подписи.")
    botx_host: str = Field("", description="FQDN BotX — audience (aud).")
    enabled: bool = Field(False, description="Включена ли проверка eXpress JWT.")


class AuthConfig(BaseModel):
    """Агрегированная конфигурация авторизации, удобная для DSL/middleware."""

    api_key: str = Field("", description="Текущий primary API-ключ.")
    jwt: JwtConfig
    express_jwt: ExpressJwtConfig


def build_auth_config(
    secure: SecureSettings | None = None, express: ExpressSettings | None = None
) -> AuthConfig:
    """Строит ``AuthConfig`` из живых ``SecureSettings``/``ExpressSettings``.

    Args:
        secure: Источник security-параметров. По умолчанию — глобальный singleton.
        express: Источник eXpress-параметров. По умолчанию — глобальный singleton.

    Returns:
        Агрегированная конфигурация авторизации.
    """
    if secure is None:
        from src.backend.core.config.security import (
            secure_settings as secure,  # noqa: PLW0127
        )
    if express is None:
        from src.backend.core.config.express import (
            express_settings as express,  # noqa: PLW0127
        )

    secret = secure.secret_key
    secret_value = (
        secret.get_secret_value()
        if hasattr(secret, "get_secret_value")
        else str(secret)
    )

    return AuthConfig(
        api_key=secure.api_key,
        jwt=JwtConfig(
            secret_key=secret_value,
            algorithm=secure.algorithm,
            token_lifetime=secure.token_lifetime,
        ),
        express_jwt=ExpressJwtConfig(
            bot_id=express.bot_id,
            secret_key=express.secret_key,
            botx_host=express.botx_host,
            enabled=express.enabled,
        ),
    )
