"""AD/LDAP directory client (K1 S6 W1 — SAML+AD login).

Назначение:
    Тонкий async-фасад над ``ldap3`` для:

    * валидации credentials (bind с user DN/password);
    * поиска пользователей в AD/LDAP по userPrincipalName/sAMAccountName;
    * resolve групп пользователя (``memberOf``);
    * чтения атрибутов (mail, displayName, department, telephoneNumber).

    Используется парой с :class:`SamlBackend`:
        * после успешного SAMLResponse получаем principal
          (NameID/email);
        * AdDirectoryClient resolve'ит группы и attribute'ы для
          authorization-policy (RBAC).

Дизайн:
    * Lazy-import ``ldap3`` — без extra'ы ``dsl-extras-3``
      импорт не падает; ``is_available()`` возвращает False.
    * Sync ``ldap3`` используется через ``asyncio.to_thread``
      (как в ``dsl/engine/processors/ldap_query.py``).
    * Capability: ``directory.read.<server>`` — проверяется на caller-side
      (entrypoints/services через ``feature_flags.saml_ad_login_enabled``).

Feature-flag:
    Активируется через ``feature_flags.saml_ad_login_enabled`` (default-OFF).
    При отключённом флаге caller должен **не** инстанцировать клиент.

Пример::

    cfg = AdServerConfig(
        server_uri="ldaps://ad.example.com:636",
        bind_dn="CN=svc-saml,OU=Service,DC=example,DC=com",
        bind_password="<from-vault>",
        search_base="DC=example,DC=com",
    )
    client = AdDirectoryClient(config=cfg)
    if not client.is_available():
        raise RuntimeError("ldap3 not installed")

    user = await client.find_user("alice@example.com")
    groups = await client.get_user_groups(user.dn)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = ("AdAuthError", "AdDirectoryClient", "AdSearchEntry", "AdServerConfig")

_logger = logging.getLogger(__name__)


class AdAuthError(Exception):
    """Ошибка bind/search/credentials в AD/LDAP.

    Используется как единая точка ошибок: invalid credentials,
    server unreachable, search filter rejected.
    """


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
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


class AdDirectoryClient:
    """Async LDAP/AD client.

    Lazy-import ``ldap3``. Если пакет не доступен,
    :meth:`is_available` возвращает False.

    Args:
        config: Параметры подключения к AD/LDAP серверу.

    Notes:
        * Caller отвечает за capability-gate ``directory.read.<server>``
          и feature-flag ``saml_ad_login_enabled``.
        * Для тестов можно инжектировать ``connection_factory`` —
          фабрика, возвращающая mock connection (см. tests/unit).
    """

    def __init__(
        self, *, config: AdServerConfig, connection_factory: Any | None = None
    ) -> None:
        """Инициализация client с config и опциональной mock-factory."""
        self._config = config
        self._connection_factory = connection_factory

    def is_available(self) -> bool:
        """Проверить, что ``ldap3`` установлен.

        Returns:
            True если LDAP client доступен; False иначе.
        """
        try:
            import ldap3  # noqa: F401, PLC0415

            return True
        except ImportError:
            return False

    async def validate_credentials(self, *, user_dn: str, password: str) -> bool:
        """Валидировать credentials пользователя через bind.

        Args:
            user_dn: DN пользователя (либо userPrincipalName для AD).
            password: Пароль пользователя.

        Returns:
            True если bind успешный, False иначе.

        Raises:
            AdAuthError: при недоступности LDAP-client'а или сервера.
        """
        if not self.is_available():
            raise AdAuthError("ldap3 не установлен")

        try:
            return await asyncio.to_thread(self._bind_sync, user_dn, password)
        except AdAuthError:
            raise
        except Exception as exc:  # noqa: BLE001 — ldap3 raises diverse exceptions
            _logger.warning("AD bind failure: %s", exc)
            return False

    def _bind_sync(self, user_dn: str, password: str) -> bool:
        """Sync bind через ldap3 (для use через ``asyncio.to_thread``)."""
        if self._connection_factory is not None:
            conn = self._connection_factory(user_dn=user_dn, password=password)
            try:
                return bool(getattr(conn, "bound", True))
            finally:
                close = getattr(conn, "unbind", None) or getattr(conn, "close", None)
                if callable(close):
                    close()

        from ldap3 import Connection, Server  # noqa: PLC0415

        srv = Server(
            self._config.server_uri,
            use_ssl=self._config.use_ssl,
            connect_timeout=int(self._config.timeout_seconds),
        )
        conn = Connection(
            srv,
            user=user_dn,
            password=password,
            auto_bind=True,
            receive_timeout=int(self._config.timeout_seconds),
        )
        try:
            return bool(conn.bound)
        finally:
            conn.unbind()

    async def find_user(self, login: str) -> AdSearchEntry | None:
        """Найти пользователя в AD по login (userPrincipalName/sAMAccountName).

        Args:
            login: Login пользователя (e.g. ``alice@example.com``).

        Returns:
            :class:`AdSearchEntry` или None если пользователь не найден.

        Raises:
            AdAuthError: при ошибке service-bind или search.
        """
        if not self.is_available():
            raise AdAuthError("ldap3 не установлен")
        if any(ch in login for ch in ("(", ")", "*", "\\", "\x00")):
            raise AdAuthError("LDAP-injection attempt: invalid chars in login")

        attrs = [
            self._config.user_id_attribute,
            self._config.group_attribute,
            "mail",
            "displayName",
            "sAMAccountName",
            "department",
            "telephoneNumber",
        ]
        search_filter = f"({self._config.user_id_attribute}={login})"
        try:
            return await asyncio.to_thread(self._search_sync, search_filter, attrs)
        except AdAuthError:
            raise
        except Exception as exc:  # noqa: BLE001 — ldap3 broad
            raise AdAuthError(f"AD search failure: {exc}") from exc

    def _search_sync(
        self, search_filter: str, attributes: Sequence[str]
    ) -> AdSearchEntry | None:
        """Sync search через ldap3 (для use через ``asyncio.to_thread``)."""
        if self._connection_factory is not None:
            conn = self._connection_factory(
                user_dn=self._config.bind_dn, password=self._config.bind_password
            )
        else:
            from ldap3 import Connection, Server  # noqa: PLC0415

            srv = Server(
                self._config.server_uri,
                use_ssl=self._config.use_ssl,
                connect_timeout=int(self._config.timeout_seconds),
            )
            conn = Connection(
                srv,
                user=self._config.bind_dn,
                password=self._config.bind_password,
                auto_bind=True,
            )

        try:
            conn.search(
                search_base=self._config.search_base,
                search_filter=search_filter,
                attributes=list(attributes),
            )
            entries = getattr(conn, "entries", []) or []
            if not entries:
                return None

            entry = entries[0]
            dn = getattr(entry, "entry_dn", "") or ""

            attr_dict: dict[str, Any] = {}
            for attr in attributes:
                if attr == self._config.group_attribute:
                    continue
                val = getattr(entry, attr, None)
                if val is None:
                    continue
                if hasattr(val, "values"):
                    raw = list(val.values)
                    attr_dict[attr] = raw[0] if len(raw) == 1 else raw
                else:
                    attr_dict[attr] = val

            groups_raw = getattr(entry, self._config.group_attribute, None)
            groups: tuple[str, ...]
            if groups_raw is None:
                groups = ()
            elif hasattr(groups_raw, "values"):
                groups = tuple(str(g) for g in groups_raw.values)
            elif isinstance(groups_raw, (list, tuple)):
                groups = tuple(str(g) for g in groups_raw)
            else:
                groups = (str(groups_raw),)

            return AdSearchEntry(dn=dn, attributes=attr_dict, groups=groups)
        finally:
            close = getattr(conn, "unbind", None) or getattr(conn, "close", None)
            if callable(close):
                close()

    async def get_user_groups(self, user_dn: str) -> tuple[str, ...]:
        """Получить DN всех групп пользователя по его DN.

        Args:
            user_dn: DN пользователя (полученный через :meth:`find_user`).

        Returns:
            Кортеж DN групп. Пустой кортеж если групп нет.

        Raises:
            AdAuthError: при ошибке service-bind или search.
        """
        if not self.is_available():
            raise AdAuthError("ldap3 не установлен")
        if any(ch in user_dn for ch in ("(", ")", "*", "\x00")):
            raise AdAuthError("LDAP-injection attempt: invalid chars in user_dn")

        try:
            entry = await asyncio.to_thread(
                self._search_sync,
                f"(distinguishedName={user_dn})",
                [self._config.group_attribute, "sAMAccountName"],
            )
        except AdAuthError:
            raise
        except Exception as exc:  # noqa: BLE001 — ldap3 broad
            raise AdAuthError(f"AD group lookup failure: {exc}") from exc

        return entry.groups if entry else ()
