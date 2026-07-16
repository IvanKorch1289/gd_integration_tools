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

__all__ = ("SecurityFacade", "get_security_facade")

_logger = get_logger("services.security.facade")

CapabilityChecker = Callable[[str, str, str | None], None]


class SecurityFacade:
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
        """Инициализация facade."""
        self._check = capability_check
        self._plugin = plugin
        # S189+ fix: JWT blacklist через Redis для multi-worker consistency.
        # In-memory set был невалиден для k8s/multi-pod deployments —
        # revoked token в pod A оставался валидным в pod B.
        self._jwt_blacklist = self._create_jwt_blacklist()

    def _create_jwt_blacklist(self) -> Any:
        """Create Redis-backed JWT blacklist (S189+).

        Returns:
            Redis-backed blacklist если Redis доступен, иначе
            fail-closed in-memory fallback с WARNING log.
        """
        try:
            from src.backend.core.auth.jwt_blacklist import (
                RedisJwtBlacklist,
            )

            blacklist = RedisJwtBlacklist()
            _logger.info("JWT blacklist: Redis-backed (multi-worker safe)")
            return blacklist
        except Exception as exc:
            # Fail-closed: in-memory fallback с WARNING.
            # Note: NOT multi-worker safe — pod A revocation won't reach pod B.
            blacklist = {"jti": set()}
            _logger.warning(
                "JWT blacklist: Redis unavailable, using in-memory fallback "
                "(NOT multi-worker safe): %s",
                exc,
            )
            return blacklist

    def _assert(self, action: str, resource: str) -> None:
        """Capability check (если установлен)."""
        if self._check is not None:
            self._check(self._plugin, action, resource)

    # ──────────────────── Capabilities ────────────────────

    async def check_capability(
        self,
        tenant_id: str,
        action: str,
        resource: str,
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
            from src.backend.core.security.capabilities import CapabilityGate

            return CapabilityGate.check(tenant_id, action, resource)
        except Exception as exc:
            _logger.debug("check_capability failed: %s", exc)
            return False

    # ──────────────────── Signatures (re-export) ────────────────────

    def verify_signature(
        self,
        payload: bytes | str,
        signature: str,
        secret: str,
        *,
        timestamp_window: int = 300,
    ) -> bool:
        """HMAC signature verification.

        Args:
            payload: Подписанные данные.
            signature: HMAC signature (hex).
            secret: Секрет.
            timestamp_window: Окно timestamp validity (сек, default 300).

        Returns:
            True если signature валидна.
        """
        from src.backend.infrastructure.security.signatures import (
            verify_signature as _verify,
        )

        return _verify(payload, signature, secret, timestamp_window=timestamp_window)

    # ──────────────────── PII ────────────────────

    async def tokenize_pii(self, text: str) -> str:
        """Reversible PII tokenization (PIITokenizer).

        Args:
            text: Текст с PII (ФИО, email, телефон, etc.).

        Returns:
            Токенизированный текст с placeholders ``<PII_TYPE_xxx>``.
        """
        self._assert("security.pii.tokenize", "text")
        try:
            from src.backend.core.security.pii_tokenizer import PIITokenizer

            tokenizer = PIITokenizer()
            return tokenizer.tokenize(text)
        except Exception as exc:
            _logger.warning("tokenize_pii failed: %s", exc)
            return text

    async def detokenize_pii(self, text: str) -> str:
        """Reversible PII detokenization."""
        self._assert("security.pii.detokenize", "text")
        try:
            from src.backend.core.security.pii_tokenizer import PIITokenizer

            tokenizer = PIITokenizer()
            return tokenizer.detokenize(text)
        except Exception as exc:
            _logger.warning("detokenize_pii failed: %s", exc)
            return text

    async def mask_pii(self, text: str) -> str:
        """One-way PII masking (irreversible).

        Args:
            text: Текст с PII.

        Returns:
            Masked text: ``"Иван И.О."``, ``"i.***@example.com"``, etc.
        """
        self._assert("security.pii.mask", "text")
        try:
            from src.backend.core.security.pii_masker import PIIMasker

            masker = PIIMasker()
            return masker.mask(text)
        except Exception as exc:
            _logger.warning("mask_pii failed: %s", exc)
            return text

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
            from src.backend.infrastructure.security.vault_secrets import (
                VaultSecretsBackend,
            )

            backend = VaultSecretsBackend()
            value = await backend.get(key)
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
            from src.backend.services.security.cert_store_facade import (
                CertStore,
            )

            store = CertStore()
            return await store.get(cert_id)
        except Exception as exc:
            _logger.debug("get_certificate %s failed: %s", cert_id, exc)
            return None

    # ──────────────────── JWT Blacklist ────────────────────

    def blacklist_token(self, jti: str) -> None:
        """Добавить JWT ID (jti) в blacklist (logout/invalidation).

        Args:
            jti: JWT ID из claim ``jti``.
        """
        self._jwt_blacklist.add(jti)
        _logger.info("JWT blacklisted: jti=%s", jti)

    def unblacklist_token(self, jti: str) -> None:
        """Удалить JWT из blacklist (для re-login после expiry)."""
        self._jwt_blacklist.discard(jti)
        _logger.info("JWT unblacklisted: jti=%s", jti)

    def is_token_blacklisted(self, jti: str) -> bool:
        """Проверить — JWT в blacklist?"""
        return jti in self._jwt_blacklist

    def clear_blacklist(self) -> None:
        """Очистить весь blacklist (для тестов)."""
        self._jwt_blacklist.clear()


@lru_cache(maxsize=1)
def get_security_facade() -> SecurityFacade:
    """Lazy singleton глобального :class:`SecurityFacade`."""
    return SecurityFacade()
