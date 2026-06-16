"""SsoRegistry (Sprint 125 W2) — per-tenant IdP configuration registry.

Per ADR-0054 §2: ``secret/data/sso/<tenant>/idp`` в Vault.
Per ADR-0054 §2: read-through cache с TTL 300 сек.
Per ADR-0054 §2: Vault audit-log invalidation (``secret_modified`` event)
                  → :meth:`SsoRegistry.invalidate` + bulk
                  :meth:`SsoRegistry.invalidate_all`.

Паттерн зеркалирует :class:`JwksCache` (TTL + asyncio.Lock + stale-fallback),
но использует Vault KV v2 вместо HTTP-эндпоинта.

**Graceful degradation:** если Vault недоступен (ENV ``VAULT_ADDR`` или
``VAULT_TOKEN`` отсутствуют, или ``hvac`` не установлен) — registry
возвращает ``None`` из :meth:`get` без crash'а. Caller решает: fail-open
(pass-through) или fail-closed (401). В :class:`require_sso_auth` (W3)
используется fail-closed для admin endpoints.

**Concurrency:** per-tenant ``asyncio.Lock`` (как :class:`JwksCache._lock`)
защищает от двойного fetch'а при concurrent cold-cache. Разные tenants
имеют разные lock'и — нет contention между ними.

**TTL invalidation:** использует ``time.monotonic()`` (как JwksCache) —
не зависит от system clock changes.

Wave: s125-w2-sso-registry
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Callable, Protocol

from pydantic import ValidationError

from src.backend.core.auth.sso_types import (
    GROUPS_TO_CAPABILITIES_KEY,
    GroupsToCapabilities,
    IdpConfig,
)
from src.backend.core.logging import get_logger

__all__ = (
    "SsoRegistry",
    "SsoRegistryError",
    "SsoRegistrySchemaError",
    "SsoRegistryVaultError",
    "VaultClientProtocol",
)

_logger = get_logger(__name__)

# Default Vault path prefix (per ADR-0054 §2): ``secret/data/sso/<tenant>/idp``.
DEFAULT_VAULT_PATH_PREFIX = "secret/data/sso"

# Default TTL 300 сек (per ADR-0054 §2).
DEFAULT_TTL_SECONDS = 300

# Sentinel для tenant path.
_TENANT_PATH_SUFFIX = "idp"


class SsoRegistryError(RuntimeError):
    """Базовая ошибка :class:`SsoRegistry` (catch-all в caller)."""


class SsoRegistrySchemaError(SsoRegistryError):
    """Pydantic validation error — config schema invalid (permanently).

    НЕ маскируется через graceful degradation: schema error значит
    config некорректен и должен быть исправлен в Vault.
    """


class SsoRegistryVaultError(SsoRegistryError):
    """Transient Vault error (connection, missing path, auth).

    Маскируется через graceful degradation в :meth:`SsoRegistry.get` —
    stale cache или ``None``.
    """


class VaultClientProtocol(Protocol):
    """Минимальный контракт Vault KV v2 reader'а.

    Production: ``hvac.Client``. Tests: fake с заранее заданным payload'ом.
    """

    def read_secret(self, path: str) -> dict[str, Any]:
        """Читает KV v2 secret.

        Args:
            path: Vault path (например, ``secret/data/sso/acme/idp``).

        Returns:
            Словарь с данными secret'а (form: ``{"data": {...}}``).

        Raises:
            Exception: Любая ошибка Vault (connection, auth, missing).
        """
        ...


class HvacVaultClient:
    """Production :class:`VaultClientProtocol` поверх ``hvac.Client``.

    Lazy-import ``hvac`` (опциональная зависимость). Если ``hvac``
    не установлен — :meth:`read_secret` бросает ``SsoRegistryError``.

    ENV vars: ``VAULT_ADDR`` (URL) + ``VAULT_TOKEN`` (auth token).
    """

    def __init__(self, *, url: str | None = None, token: str | None = None) -> None:
        self._url = url or os.environ.get("VAULT_ADDR")
        self._token = token or os.environ.get("VAULT_TOKEN")
        self._client: Any | None = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import hvac  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SsoRegistryVaultError(
                "hvac not installed; установите 'hvac' для production Vault"
            ) from exc
        if not (self._url and self._token):
            raise SsoRegistryVaultError(
                "VAULT_ADDR и VAULT_TOKEN обязательны для HvacVaultClient"
            )
        self._client = hvac.Client(url=self._url, token=self._token)
        return self._client

    def read_secret(self, path: str) -> dict[str, Any]:
        client = self._ensure_client()
        try:
            resp = client.secrets.kv.v2.read_secret_version(path=path)
        except Exception as exc:
            raise SsoRegistryVaultError(
                f"Vault read failed for {path!r}: {exc}"
            ) from exc
        # KV v2 формат: {"data": {"data": {...}, "metadata": {...}}}.
        return resp.get("data", {}).get("data", {}) or {}


class SsoRegistry:
    """Per-tenant IdP configuration registry (read-through cache).

    Args:
        vault_path_prefix: Vault path prefix. Default ``"secret/data/sso"``.
        ttl: TTL кеша в секундах. Default 300 (per ADR-0054).
        vault_client: Production :class:`VaultClientProtocol` (default:
            :class:`HvacVaultClient`).

    Attrs:
        vault_path_prefix: Vault path prefix.

    Example::

        registry = SsoRegistry()  # uses HvacVaultClient
        idp_config = await registry.get("acme")
        if idp_config is None:
            raise HTTPException(503, "IdP config not available")
    """

    def __init__(
        self,
        *,
        vault_path_prefix: str = DEFAULT_VAULT_PATH_PREFIX,
        ttl: int = DEFAULT_TTL_SECONDS,
        vault_client: VaultClientProtocol | None = None,
    ) -> None:
        self.vault_path_prefix = vault_path_prefix
        self._ttl = ttl
        self._vault = vault_client or HvacVaultClient()
        self._cache: dict[str, IdpConfig] = {}
        self._expires_at: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    def _path_for(self, tenant: str) -> str:
        """Vault path для tenant'а: ``<prefix>/<tenant>/idp``."""
        return f"{self.vault_path_prefix}/{tenant}/{_TENANT_PATH_SUFFIX}"

    def _lock_for(self, tenant: str) -> asyncio.Lock:
        """Per-tenant asyncio.Lock (lazy-create под global lock'ом)."""
        lock = self._locks.get(tenant)
        if lock is not None:
            return lock
        # Создание нового lock вне global lock'а безопасно (asyncio.Lock
        # creation не имеет side effects).
        new_lock = asyncio.Lock()
        self._locks[tenant] = new_lock
        return new_lock

    def _is_fresh(self, tenant: str) -> bool:
        expires_at = self._expires_at.get(tenant)
        return (
            tenant in self._cache
            and expires_at is not None
            and time.monotonic() < expires_at
        )

    async def _load(self, tenant: str) -> IdpConfig:
        """Читает IdP config из Vault и парсит через Pydantic.

        Raises:
            SsoRegistryVaultError: Transient Vault error (masked в
                :meth:`get` через stale-fallback).
            SsoRegistrySchemaError: Pydantic validation error ИЛИ
                missing required field (propagates — schema error значит
                config некорректен, нужно fix в Vault).
        """
        path = self._path_for(tenant)
        raw = self._vault.read_secret(path)
        try:
            return _parse_idp_config(raw)
        except (ValidationError, KeyError) as exc:
            raise SsoRegistrySchemaError(
                f"Invalid IdP config schema at {path!r}: {exc}"
            ) from exc

    async def get(self, tenant: str) -> IdpConfig | None:
        """Возвращает IdP config для tenant'а (с read-through cache).

        Args:
            tenant: Tenant ID.

        Returns:
            :class:`IdpConfig` или ``None`` если Vault недоступен
            (graceful degradation) И нет cached value.

        Raises:
            SsoRegistrySchemaError: Pydantic validation error (propagates).
        """
        if self._is_fresh(tenant):
            return self._cache[tenant]
        lock = self._lock_for(tenant)
        async with lock:
            # Re-check после acquire lock'а (double-checked locking).
            if self._is_fresh(tenant):
                return self._cache[tenant]
            try:
                config = await self._load(tenant)
            except SsoRegistryVaultError as exc:
                # Stale-fallback (как JwksCache): если есть cached value —
                # возвращаем его с warning.
                if tenant in self._cache:
                    _logger.warning(
                        "SsoRegistry refresh failed for %r (%s); using stale cache",
                        tenant,
                        exc,
                    )
                    return self._cache[tenant]
                _logger.error("SsoRegistry load failed for %r: %s", tenant, exc)
                return None
            # SsoRegistrySchemaError propagates (caller decides).
            self._cache[tenant] = config
            self._expires_at[tenant] = time.monotonic() + self._ttl
            return config

    def invalidate(self, tenant: str) -> None:
        """Ручная инвалидация кеша для tenant'а.

        Вызывается из Vault audit-log listener'а на ``secret_modified``
        event (per ADR-0054 §2).
        """
        self._cache.pop(tenant, None)
        self._expires_at.pop(tenant, None)

    def invalidate_all(self) -> None:
        """Bulk-инвалидация всего кеша (для scheduled refresh-cron).

        Per ADR-0054 §4: refresh-cron ``0 3 * * *`` обновляет IdP-метаданные
        в Vault. После refresh все cached configs могут быть stale → mass
        invalidation.
        """
        self._cache.clear()
        self._expires_at.clear()


def _parse_idp_config(raw: dict[str, Any]) -> IdpConfig:
    """Парсит raw Vault payload → :class:`IdpConfig`.

    Ожидаемый формат (per ADR-0054 §2)::

        {
            "entity_id": "https://idp.example.com/saml",
            "sso_url": "https://idp.example.com/sso",
            "x509_cert": "-----BEGIN CERTIFICATE-----\\n...",
            "slo_url": "https://idp.example.com/slo",  # optional
            "allow_create_user": true,
            "groups_to_capabilities": {
                "bank-admins": ["admin.feature_flag:write", ...],
                ...
            }
        }

    Raises:
        KeyError: Если отсутствуют required fields (``entity_id``,
            ``sso_url``, ``x509_cert``). Caller (``_load``) ловит и
            оборачивает в :class:`SsoRegistrySchemaError`.
        ValidationError: Если типы полей некорректны.
    """
    groups_to_caps_raw = raw.get(GROUPS_TO_CAPABILITIES_KEY, {}) or {}
    return IdpConfig(
        entity_id=raw["entity_id"],
        sso_url=raw["sso_url"],
        x509_cert=raw["x509_cert"],
        slo_url=raw.get("slo_url"),
        allow_create_user=raw.get("allow_create_user", False),
        groups_to_capabilities=GroupsToCapabilities(mappings=groups_to_caps_raw),
    )


# Type alias for custom Vault client factory.
VaultClientFactory = Callable[[], VaultClientProtocol]
