"""LDAP/AD client factory (S58 W6b).

Singleton wrapper над :class:`AdDirectoryClient` который:
* лениво инстанцирует client при первом вызове (после проверки
  feature flag ``saml_ad_login_enabled``);
* читает конфигурацию из :data:`ldap_settings` (см. ``config.services.ldap``);
* безопасно отключается (no-op) при отсутствии LDAP-модуля или feature flag = OFF;
* singleton на уровне процесса (module-level cache).

Использование::

    from src.backend.core.auth.ldap_client_factory import get_ad_client

    client = get_ad_client()
    if client is None:
        raise HTTPException(503, "LDAP auth is not enabled or configured")
    ad_user = await client.find_user("alice@example.com")

Почему не DI/inject: ``AdDirectoryClient`` создаётся ОДИН раз на
process (per-env). Это соответствует pattern других core clients
(см. ``core/auth/jwt_backend.py``, ``core/auth/api_key_backend.py``).
"""

from __future__ import annotations

from src.backend.core.logging import get_logger
from typing import Any

from src.backend.services.auth.ad_directory_client import (
    AdDirectoryClient,
    AdServerConfig,
)

__all__ = ("get_ad_client", "reset_ad_client", "ad_client_cached")

_logger = get_logger(__name__)

# Singleton cache. ``None`` = ещё не инстанцирован.
# ``False`` = инстанциация провалилась (не enable'нули) → кэшируем False.
_ad_client_instance: AdDirectoryClient | None = None
_ad_client_attempted: bool = False


def ad_client_cached() -> bool:
    """``True`` если client успешно инстанцирован (singleton cache populated)."""
    return _ad_client_instance is not None


def reset_ad_client() -> None:
    """Сброс singleton cache. Используется в тестах."""
    global _ad_client_instance, _ad_client_attempted
    _ad_client_instance = None
    _ad_client_attempted = False


def get_ad_client(
    *, feature_flag_enabled: bool | None = None, connection_factory: Any | None = None
) -> AdDirectoryClient | None:
    """Возвращает singleton :class:`AdDirectoryClient` или ``None``.

    Args:
        feature_flag_enabled: Если передан — caller контролирует проверку
            feature flag (``saml_ad_login_enabled``). Если None — factory
            сам читает из settings (``ldap_settings.is_configured()``).
        connection_factory: Mock-фабрика для тестов (передаётся в
            :class:`AdDirectoryClient` для подмены ``ldap3.Connection``).

    Returns:
        :class:`AdDirectoryClient` если LDAP сконфигурирован и feature
        flag ON; ``None`` иначе (NO exception, no side-effect).

    Notes:
        * Не бросает :class:`AdAuthError` — caller получает ``None`` и
          решает, что делать (HTTP 503, fallback на password, etc.).
        * ``ldap3`` optional — если не установлен, ``is_available()``
          возвращает False, но factory не падает (для unit-тестов
          без LDAP).
    """
    global _ad_client_instance, _ad_client_attempted

    if _ad_client_instance is not None:
        return _ad_client_instance

    if _ad_client_attempted and _ad_client_instance is None:
        return None  # Уже пытались инстанцировать — провалилось

    _ad_client_attempted = True

    # Проверка feature flag (если caller передал)
    if feature_flag_enabled is False:
        _logger.debug("get_ad_client: feature flag disabled, no client")
        return None

    # Lazy lookup ldap_settings (для testability — patch через module-level)
    from src.backend.core.config.services import ldap as _ldap_module

    settings = _ldap_module.ldap_settings
    if not settings.is_configured():
        _logger.debug("get_ad_client: ldap_settings not configured, no client")
        return None

    # Конструируем AdServerConfig → AdDirectoryClient
    config = AdServerConfig(
        server_uri=settings.server_uri,
        bind_dn=settings.bind_dn,
        bind_password=settings.bind_password,
        search_base=settings.search_base,
        use_ssl=settings.use_ssl,
        timeout_seconds=settings.timeout_seconds,
        user_id_attribute=settings.user_id_attribute,
        group_attribute=settings.group_attribute,
    )
    client = AdDirectoryClient(config=config, connection_factory=connection_factory)
    _ad_client_instance = client
    _logger.info(
        "get_ad_client: instantiated AdDirectoryClient for %s", settings.server_uri
    )
    return client
