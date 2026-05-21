"""Пакет ``services/auth`` — auth-сервисы плагин-уровня (K1 S6).

Назначение:
    Сервисы, работающие с внешними auth-системами (AD/LDAP, IdP'и),
    отделены от ``core/auth/`` (Protocols + value-objects) и
    ``infrastructure/auth/`` (адаптеры/clients). Здесь лежат
    директорные клиенты — обёртки над ``ldap3``/``aioldap3`` для
    AD lookups, валидации credentials и group resolution.

Содержимое:
    * :class:`AdDirectoryClient` — LDAP/AD сервис: bind / search /
      validate_credentials / get_user_groups.

Зависимости (optional extra ``dsl-extras-3``):
    * ``aioldap3>=1.0`` — async LDAP client (предпочтительный);
    * ``ldap3>=2.9`` — sync LDAP client (fallback через
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
