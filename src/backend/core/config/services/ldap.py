"""LDAP/AD server connection settings (S58 W6a).

Глобальная single-tenant конфигурация LDAP-сервера (per design S58 W6):
* ``LDAP_SERVER_URI`` — ``ldap://`` или ``ldaps://`` (для prod обязателен ldaps);
* ``LDAP_BIND_DN`` / ``LDAP_BIND_PASSWORD`` — service-account credentials
  (для search/bind операций; никогда не используется для user-credentials);
* ``LDAP_SEARCH_BASE`` — base DN для user-lookup (``DC=example,DC=com``);
* ``LDAP_USE_SSL`` — auto-derive из URI (``ldaps://`` → True), но можно override;
* ``LDAP_TIMEOUT_SECONDS`` — TCP connect-timeout (default 10s);
* ``LDAP_USER_ID_ATTRIBUTE`` — атрибут для поиска по login
  (default ``userPrincipalName``; для legacy AD — ``sAMAccountName``);
* ``LDAP_GROUP_ATTRIBUTE`` — атрибут с DN групп (default ``memberOf``).

Совместимость:
* ``ldap3`` — optional dep (``dsl-extras-3``); ``AdDirectoryClient.is_available()``
  проверяет наличие.
* Feature-flag ``feature_flags.saml_ad_login_enabled`` (default OFF) —
  caller обязан проверять ПЕРЕД инстанцированием client (см. ADR-0085).
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("LdapSettings", "ldap_settings")


class LdapSettings(BaseSettingsWithLoader):
    """Pydantic-settings для LDAP/AD server.

    Yaml-группа: ``ldap`` (settings.yaml → ``ldap: { ... }``).
    Env-префикс: ``LDAP_`` (env vars → ``LDAP_SERVER_URI=ldaps://...``).
    """

    yaml_group: ClassVar[str] = "ldap"  # type: ignore[misc]
    model_config = SettingsConfigDict(env_prefix="LDAP_", extra="forbid")

    # === Обязательные параметры ===

    server_uri: str = Field(
        default="",
        description=(
            "URI LDAP-сервера: ldap://host:389 или ldaps://host:636. "
            "Production обязателен ldaps:// или START_TLS."
        ),
        example="ldaps://ad.example.com:636",
    )
    bind_dn: str = Field(
        default="",
        description=(
            "DN service-account для search/bind операций "
            "(например, ``CN=svc-saml,OU=Service,DC=example,DC=com``). "
            "Пароль — ``bind_password`` (см. SecretBroker integration)."
        ),
        example="CN=svc-saml,OU=Service,DC=example,DC=com",
    )
    bind_password: str = Field(
        default="",
        description=(
            "Пароль service-account. В production брать из SecretBroker "
            "(HashiCorp Vault / sealed-secrets), НЕ из env vars."
        ),
    )
    search_base: str = Field(
        default="",
        description="Base DN для user-lookup (например, ``DC=example,DC=com``).",
        example="DC=example,DC=com",
    )

    # === Опциональные параметры (default values подходят для AD 2016+) ===

    use_ssl: bool = Field(
        default=False,
        description=(
            "True для ``ldaps://``. Авто-derive из ``server_uri`` "
            "(если URI начинается с ``ldaps://`` → True). Override возможен."
        ),
    )
    timeout_seconds: float = Field(
        default=10.0,
        gt=0.0,
        le=120.0,
        description="TCP connect-timeout в секундах (default 10s, max 120s).",
    )
    user_id_attribute: str = Field(
        default="userPrincipalName",
        description=(
            "Атрибут для поиска по login. Default ``userPrincipalName`` "
            "(email-формат, modern AD). Для legacy AD — ``sAMAccountName``."
        ),
    )
    group_attribute: str = Field(
        default="memberOf",
        description="Атрибут с DN групп пользователя (default ``memberOf``).",
    )

    def is_configured(self) -> bool:
        """Все 4 обязательных параметра заданы (server_uri/bind_dn/password/base)."""
        return bool(self.server_uri and self.bind_dn and self.bind_password and self.search_base)


ldap_settings = LdapSettings()  # type: ignore[call-arg]
