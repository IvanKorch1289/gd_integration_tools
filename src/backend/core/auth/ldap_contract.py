"""Core-контракты для создания LDAP/AD клиента.

Конкретная реализация регистрируется composition-слоем через DI provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class AdServerConfig:
    """Конфигурация подключения к LDAP/AD серверу.

    Attributes:
        server_uri: URI LDAP-сервера.
        bind_dn: DN сервисной учётной записи.
        bind_password: Пароль сервисной учётной записи.
        search_base: Базовый DN поиска.
        use_ssl: Использовать TLS-соединение.
        timeout_seconds: Таймаут подключения в секундах.
        user_id_attribute: Атрибут идентификатора пользователя.
        group_attribute: Атрибут групп пользователя.
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
        """Включить TLS автоматически для ``ldaps://`` URI."""
        if self.server_uri.startswith("ldaps://"):
            object.__setattr__(self, "use_ssl", True)


class AdDirectoryClientProtocol(Protocol):
    """Минимальный контракт LDAP-клиента, используемый core factory."""

    def is_available(self) -> bool:
        """Вернуть признак доступности LDAP-драйвера."""


class AdDirectoryClientFactory(Protocol):
    """Фабрика конкретного LDAP-клиента из composition-слоя."""

    def __call__(
        self,
        *,
        config: AdServerConfig,
        connection_factory: Any | None = None,
    ) -> AdDirectoryClientProtocol:
        """Создать LDAP-клиент с заданной конфигурацией."""


__all__ = (
    "AdDirectoryClientFactory",
    "AdDirectoryClientProtocol",
    "AdServerConfig",
)
