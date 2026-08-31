"""Пакет ``services/auth`` — auth-сервисы плагин-уровня (K1 S6).

Назначение:
    Сервисы, работающие с внешними auth-системами (AD/LDAP, IdP'и),
    отделены от ``core/auth/`` (Protocols + value-objects) и
    ``infrastructure/auth/`` (адаптеры/clients). Здесь лежат
    директорные клиенты — обёртки над ``ldap3`` для
    AD lookups, валидации credentials и group resolution.

Содержимое:
    * :class:`AdDirectoryClient` — async AD/LDAP client с методами
      validate_credentials / get_user_groups.

Зависимости (optional extra ``dsl-extras-3``):
    * ``ldap3>=3.4`` — sync LDAP client (used via
      ``asyncio.to_thread``).

Capability:
    Все обращения подлежат capability-gate (``directory.read.<server>``)
    и идут через feature-flag ``saml_ad_login_enabled``.
"""

from __future__ import annotations

from src.backend.services.auth.ad_directory_client import (
    AdAuthError,
    AdDirectoryClient,
    AdSearchEntry,
    AdServerConfig,
)

__all__ = ("AdAuthError", "AdDirectoryClient", "AdSearchEntry", "AdServerConfig")
