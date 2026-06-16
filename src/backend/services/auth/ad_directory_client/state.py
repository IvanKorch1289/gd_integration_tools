"""S67 W4 - state.py part of ad_directory_client decomp.

Per-class file split.

Classes: AdAuthError, AdServerConfig, AdSearchEntry.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger(__name__)


class AdAuthError(Exception):
    """Ошибка bind/search/credentials в AD/LDAP.

    Используется как единая точка ошибок: invalid credentials,
    server unreachable, search filter rejected.
    """


@dataclass
class AdServerConfig:
    """Конфигурация AD/LDAP сервера.

    Attributes:
        server_uri: Полный URI сервера (``ldap://`` или ``ldaps://``).
            Для production обязателен ``ldaps://`` или START_TLS.
        bind_dn: DN для service-account bind (e.g. ``CN=svc-saml,DC=...``).
        bind_password: Пароль service-account (через :class:`SecretBroker`).
        search_base: Base DN для поиска пользователей (``DC=example,DC=com``).
        use_ssl: True для ``ldaps://``. Если URI содержит ``ldaps`` —
            считается True автоматически (см. ``__post_init__``).
        timeout_seconds: TCP connect-timeout (default 10s).
        user_id_attribute: Атрибут для поиска по login (по умолчанию
            ``userPrincipalName``; для legacy AD — ``sAMAccountName``).
        group_attribute: Атрибут с DN групп пользователя (default ``memberOf``).
    """

    server_uri: str
    bind_dn: str
    bind_password: str
    search_base: str
    use_ssl: bool = field(default=False)
    timeout_seconds: float = 10.0
    user_id_attribute: str = "userPrincipalName"
    group_attribute: str = "memberOf"

    def __post_init__(self) -> None:
        """Автоматически выставляет ``use_ssl=True`` для ldaps:// URI."""
        if self.server_uri.startswith("ldaps://"):
            object.__setattr__(self, "use_ssl", True)


@dataclass
class AdSearchEntry:
    """Результат AD search.

    Attributes:
        dn: Distinguished Name пользователя.
        attributes: Атрибуты пользователя (mail/displayName/department/...).
        groups: DN всех групп пользователя (resolve'нные через memberOf).
    """

    dn: str
    attributes: Mapping[str, Any]
    groups: tuple[str, ...] = ()
