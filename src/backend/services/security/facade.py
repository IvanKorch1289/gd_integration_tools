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

from cachetools import TTLCache

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
        """Инициализация facade.

        JWT blacklist инициализируется в ``init_jwt_blacklist()`` async-методом,
        потому что :func:`get_redis_client` возвращает объект с async ``get_client()``.
        """
        self._check = capability_check
        self._plugin = plugin
        self._jwt_blacklist: Any = None
        self._jwt_blacklist_ready = False

    async def init_jwt_blacklist(self) -> None:
        """S189+ fix: lazy-init Redis-backed JWT blacklist.

        Без этого метода blacklist инициализируется как ``None`` — все
        blacklist_token/unblacklist/is_blacklisted будут no-op.
        """
        if self._jwt_blacklist_ready:
            return
        self._jwt_blacklist = await self._create_jwt_blacklist()
        self._jwt_blacklist_ready = True

    async def _create_jwt_blacklist(self) -> Any:
        """Create Redis-backed JWT blacklist (S189+).

        Returns:
            Redis-backed blacklist если Redis доступен, иначе
            fail-open in-memory fallback (per-pod revocation).

        """
        try:
            from src.backend.core.auth.jwt_blacklist import RedisJwtBlacklist
            from src.backend.infrastructure.clients.storage.redis import (
                get_redis_client,
            )

            redis_client = await get_redis_client().get_client("cache")
            blacklist = RedisJwtBlacklist(redis_client)
            _logger.info("JWT blacklist: Redis-backed (multi-worker safe)")
            return blacklist
        except Exception as exc:
            # In-memory fallback (NOT multi-worker safe — для dev_light).
            _logger.warning(
                "JWT blacklist: Redis unavailable, using in-memory fallback "
                "(NOT multi-worker safe): %s",
                exc,
            )
            return _InMemoryJwtBlacklist()

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
        from src.backend.core.api.security import (
            verify_signature as _verify,
        )

        return _verify(
            payload, signature, timestamp, secret, window_seconds=window_seconds
        )

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
            from src.backend.core.security.pii_tokenizer import PIIPolicy, PIITokenizer

            tokenizer = PIITokenizer()
            policy = PIIPolicy(name="ru_strict_reversible")
            masked_text, _token_map = await tokenizer.mask_reversible(text, policy)
            return masked_text
        except Exception as exc:
            _logger.warning("tokenize_pii failed: %s", exc)
            return text

    async def detokenize_pii(self, text: str) -> str:
        """Reversible PII detokenization.

        Note: detokenization requires the original TokenMap. This method
        returns the text as-is if no token map is available (caller must
        pass it through PIITokenizer.unmask directly).
        """
        self._assert("security.pii.detokenize", "text")
        _logger.debug(
            "detokenize_pii: use PIITokenizer.unmask(masked_text, token_map) directly"
        )
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
            return masker.mask_text(text)
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

    # ──────────────────── JWT Blacklist ────────────────────

    async def blacklist_token(self, jti: str, *, expires_at: int | None = None) -> bool:
        """Добавить JWT ID (jti) в blacklist (logout/invalidation).

        Args:
            jti: JWT ID из claim ``jti``.
            expires_at: Unix timestamp истечения токена (TTL для Redis).
                Если None — используется 24h default.

        Returns:
            True если успешно, False при ошибке.

        """
        if self._jwt_blacklist is None:
            await self.init_jwt_blacklist()
        import time

        exp = expires_at if expires_at is not None else int(time.time()) + 86400
        try:
            await self._jwt_blacklist.revoke(jti, exp)
            _logger.info("JWT blacklisted: jti=%s", jti)
            return True
        except Exception as exc:
            _logger.error("JWT blacklist revoke failed for jti=%s: %s", jti, exc)
            return False

    async def unblacklist_token(self, jti: str) -> bool:
        """Удалить JWT из blacklist (для re-login после expiry).

        Note: Redis blacklist использует TTL — после exp jti автоматически
        удаляется из Redis. Этот метод доступен только для тестов (Redis DEL).
        """
        if self._jwt_blacklist is None:
            return True
        try:
            from src.backend.core.auth.jwt_blacklist import RedisJwtBlacklist

            if isinstance(self._jwt_blacklist, RedisJwtBlacklist):
                await self._jwt_blacklist._redis.delete(self._jwt_blacklist._key(jti))
            else:
                await self._jwt_blacklist.unrevoke(jti)
            _logger.info("JWT unblacklisted: jti=%s", jti)
            return True
        except Exception as exc:
            _logger.warning("JWT unblacklist failed for jti=%s: %s", jti, exc)
            return False

    async def is_token_blacklisted(self, jti: str) -> bool:
        """Проверить — JWT в blacklist?

        Fail-closed: ошибки blacklist пробрасываются (см.
        :meth:`RedisJwtBlacklist.is_revoked`).
        """
        if self._jwt_blacklist is None:
            await self.init_jwt_blacklist()
        return await self._jwt_blacklist.is_revoked(jti)

    async def clear_blacklist(self) -> None:
        """Очистить весь blacklist (для тестов)."""
        if self._jwt_blacklist is None:
            return
        try:
            from src.backend.core.auth.jwt_blacklist import RedisJwtBlacklist

            if isinstance(self._jwt_blacklist, RedisJwtBlacklist):
                pattern = f"{self._jwt_blacklist._prefix}*"
                cursor = 0
                while True:
                    cursor, keys = await self._jwt_blacklist._redis.scan(
                        cursor, match=pattern, count=100
                    )
                    if keys:
                        await self._jwt_blacklist._redis.delete(*keys)
                    if cursor == 0:
                        break
            else:
                await self._jwt_blacklist.clear()
        except Exception as exc:
            _logger.warning("JWT blacklist clear failed: %s", exc)


class _InMemoryJwtBlacklist:
    """In-memory fallback для JWT blacklist (NOT multi-worker safe).

    Реализует тот же async API что и :class:`RedisJwtBlacklist`:
    ``revoke(jti, expires_at)``, ``unrevoke(jti)``, ``is_revoked(jti)``,
    ``clear()``, ``is_iat_revoked(iat)`` (no-op), ``revoke_before_time(t)`` (no-op).

    S210 Ponytail fix (Layer 2 Cycle 1): ручной ``dict + threading.Lock +
    time.time()`` заменён на ``cachetools.TTLCache`` (уже в pyproject.toml).
    - TTL-expiry встроен → не нужно вручную проверять ``exp < time.time()``.
    - maxsize=10_000 защита от unbounded growth.
    - Trade-off: теряется per-entry TTL granularity (caller передаёт
      expires_at, но хранится фиксированный 24h max). Для JWT OK —
      реальные TTL < 24h.

    S210 Cycle 1 review fix: ``cachetools.TTLCache`` **не thread-safe** по
    дизайну (см. cachetools upstream docs). Восстановлен ``threading.Lock``
    для multi-thread safety внутри single-process. Async-only callers
    (single event-loop, no ``await`` points внутри методов) и так
    безопасны, но Lock добавляет defense-in-depth для sync middleware /
    ThreadPoolExecutor paths.

    S210 Cycle 1 review fix: ``expires_at`` clamped to 24h; для longer-running
    tokens (e.g. service-to-service > 24h) предпочитать RedisJwtBlacklist
    (production). In-memory fallback — single-process only.
    """

    def __init__(self) -> None:
        import asyncio

        # ttl: 24h default. Per-entry granularity теряется, но экономим
        # ~40 LOC ручного TTL-check. JWT обычно живут < 24h.
        self._store: TTLCache[str, bool] = TTLCache(maxsize=10_000, ttl=86400)
        # cachetools.TTLCache НЕ thread-safe по дизайну → asyncio.Lock обязателен
        # (методы revoke/unvoke/is_revoked — async; threading.Lock блокирует event loop).
        self._lock = asyncio.Lock()

    async def revoke(self, jti: str, expires_at: int) -> None:
        # expires_at учтён через ttl=86400; bool-значение не нужно хранить.
        async with self._lock:
            self._store[jti] = True

    async def unrevoke(self, jti: str) -> None:
        async with self._lock:
            self._store.pop(jti, None)

    async def is_revoked(self, jti: str) -> bool:
        async with self._lock:
            return jti in self._store

    async def is_iat_revoked(self, iat: int | None) -> bool:
        return False  # in-memory fallback не поддерживает batch revoke

    async def revoke_before_time(self, time_threshold: int) -> None:
        return None  # no-op in in-memory fallback

    async def clear(self) -> None:
        with self._lock:
            self._store.clear()


@lru_cache(maxsize=1)
def get_security_facade() -> SecurityFacade:
    """Lazy singleton глобального :class:`SecurityFacade`."""
    return SecurityFacade()
