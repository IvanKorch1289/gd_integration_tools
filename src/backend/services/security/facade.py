"""SecurityFacade — unified capability-checked facade для security primitives.

Sprint S183 (Security domain): закрывает критический gap — ранее
``services/security/`` содержал только signatures re-export.
Теперь — единая точка входа для extensions / DSL:

- ``check_capability()`` — проверить capability для tenant/action/resource
- ``verify_signature()`` — HMAC signature verification (re-export из signatures)
- ``tokenize_pii()`` / ``detokenize_pii()`` — reversible PII redaction
- ``mask_pii()`` — one-way PII masking
- ``get_secret()`` — typed secret access (Vault / Env / File)
- ``get_certificate()`` — typed cert access (Vault / Consul / File)
- ``blacklist_token()`` — JWT blacklist для logout/invalidation
- ``is_token_blacklisted()`` — check blacklist

Ponytail: thin wrapper, не дублирует логику. Делегирует через DI.

S3 (ledger, 2026-09-05): сплит god-object (453 LOC / 22 методов) по
паттерну закрытых M2-сплитов — зоны вынесены в миксины:
:mod:`facade_pii` (PII-операции) и :mod:`facade_blacklist` (JWT blacklist).
Обратная совместимость: все публичные имена доступны отсюда.

Использование::

    from src.backend.services.security.facade import get_security_facade

    facade = get_security_facade()
    if await facade.check_capability(tenant_id, "ds.read", "user:42"):
        await facade.tokenize_pii(body)
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.services.security.facade_blacklist import JwtBlacklistMixin
from src.backend.services.security.facade_blacklist import (
    _InMemoryJwtBlacklist as _InMemoryJwtBlacklist,  # noqa: F401 — back-compat
)
from src.backend.services.security.facade_pii import PiiFacadeMixin

__all__ = ("SecurityFacade", "get_security_facade")

_logger = get_logger("services.security.facade")

CapabilityChecker = Callable[[str, str, str | None], None]


class SecurityFacade(
    JwtBlacklistMixin,
    PiiFacadeMixin,
):
    """Unified capability-checked facade для security primitives.

    Args:
        capability_check: Опц. callback ``CapabilityGate.check``.
        plugin: Имя caller'а (для capability-event и audit).

    """

    def __init__(
        self,
        *,
        capability_check: CapabilityChecker | None = None,
        plugin: str = "extension",
    ) -> None:
        """Инициализация facade.

        JWT blacklist инициализируется в ``init_jwt_blacklist()`` async-методом,
        потому что :func:`get_redis_client` возвращает объект с async ``get_client()``.
        """
        self._check = capability_check
        self._plugin = plugin
        self._jwt_blacklist: Any = None
        self._jwt_blacklist_ready = False

    def _assert(self, action: str, resource: str) -> None:
        """Capability check (если установлен)."""
        if self._check is not None:
            self._check(self._plugin, action, resource)

    # ──────────────────── Capabilities ────────────────────

    async def check_capability(
        self, tenant_id: str, action: str, resource: str
    ) -> bool:
        """Проверить capability для tenant.

        Args:
            tenant_id: Идентификатор тенанта.
            action: Capability action (e.g., ``"ds.read"``).
            resource: Resource scope (e.g., ``"user:42"``).

        Returns:
            True если capability granted, False иначе.

        """
        try:
            from src.backend.services.capabilities.facade import get_capability_facade

            return get_capability_facade().check(tenant_id, action, resource)
        except Exception as exc:
            _logger.debug("check_capability failed: %s", exc)
            return False

    # ──────────────────── Signatures (re-export) ────────────────────

    def verify_signature(
        self,
        payload: bytes | str,
        signature: str,
        timestamp: int,
        secret: str,
        *,
        window_seconds: int = 300,
    ) -> bool:
        """HMAC signature verification.

        Args:
            payload: Подписанные данные.
            signature: HMAC signature (hex).
            timestamp: Unix timestamp из header.
            secret: Секрет.
            window_seconds: Окно timestamp validity (сек, default 300).

        Returns:
            True если signature валидна.

        """
        from src.backend.infrastructure.security.signatures import (
            verify_signature as _verify,
        )

        return _verify(
            payload, signature, timestamp, secret, window_seconds=window_seconds
        )

    # ──────────────────── Secrets ────────────────────

    async def get_secret(self, key: str, *, default: str | None = None) -> str | None:
        """Получить secret из Vault/Env/File backend.

        Args:
            key: Secret key (e.g., ``"api.openai"``).
            default: Default если secret не найден.

        Returns:
            Secret value или default.

        """
        self._assert("security.secret.read", key)
        try:
            from src.backend.core.interfaces.secrets import SecretsBackend
            from src.backend.core.svcs_registry import get_service

            backend = get_service(SecretsBackend)
            value = await backend.get_secret(key)
            return value if value is not None else default
        except Exception as exc:
            _logger.debug("get_secret %s failed: %s", key, exc)
            return default

    # ──────────────────── Certificates ────────────────────

    async def get_certificate(self, cert_id: str) -> bytes | None:
        """Получить TLS certificate по cert_id.

        Args:
            cert_id: Cert identifier.

        Returns:
            PEM bytes или None если не найден.

        """
        self._assert("security.cert.read", cert_id)
        try:
            from src.backend.services.security.cert_store_facade import CertStore

            store = CertStore()
            return await store.get(cert_id)
        except Exception as exc:
            _logger.debug("get_certificate %s failed: %s", cert_id, exc)
            return None


@lru_cache(maxsize=1)
def get_security_facade() -> SecurityFacade:
    """Lazy singleton глобального :class:`SecurityFacade`."""
    return SecurityFacade()
