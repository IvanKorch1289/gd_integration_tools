"""JWT-blacklist зона SecurityFacade (S3 сплит, из facade.py).

S3 (ledger, 2026-09-05): выделение зон ответственности из
``services/security/facade.py`` (453 LOC / 22 методов) по паттерну
закрытых M2-сплитов. Mixin хранит состояние в ``self._jwt_blacklist`` /
``self._jwt_blacklist_ready`` (инициализация — в ядре facade).
"""

from __future__ import annotations

from typing import Any

from cachetools import TTLCache

from src.backend.core.logging import get_logger

_logger = get_logger("services.security.facade")


class InMemoryJwtBlacklist:
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
    дизайну (см. cachetools upstream docs). Восстановлен ``asyncio.Lock``
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


# Backward-compat: историческое имя (tests/unit/services/test_security_facade_jwt.py).
_InMemoryJwtBlacklist = InMemoryJwtBlacklist


class JwtBlacklistMixin:
    """JWT-blacklist операции facade (logout/invalidation)."""

    async def init_jwt_blacklist(self) -> None:
        """S189+ fix: lazy-init Redis-backed JWT blacklist.

        Без этого метода blacklist инициализируется как ``None`` — все
        blacklist_token/unblacklist/is_blacklisted будут no-op.
        """
        if self._jwt_blacklist_ready:  # type: ignore[attr-defined]
            return
        self._jwt_blacklist = await self._create_jwt_blacklist()  # type: ignore[attr-defined]
        self._jwt_blacklist_ready = True  # type: ignore[attr-defined]

    async def _create_jwt_blacklist(self) -> Any:
        """Create Redis-backed JWT blacklist (S189+).

        Returns:
            Redis-backed blacklist если Redis доступен, иначе
            fail-open in-memory fallback (per-pod revocation).

        """
        try:
            from src.backend.core.api.storage import get_redis_client
            from src.backend.core.auth.jwt_blacklist import RedisJwtBlacklist

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

    async def blacklist_token(self, jti: str, *, expires_at: int | None = None) -> bool:
        """Добавить JWT ID (jti) в blacklist (logout/invalidation).

        Args:
            jti: JWT ID из claim ``jti``.
            expires_at: Unix timestamp истечения токена (TTL для Redis).
                Если None — используется 24h default.

        Returns:
            True если успешно, False при ошибке.

        """
        if self._jwt_blacklist is None:  # type: ignore[attr-defined]
            await self.init_jwt_blacklist()
        import time

        exp = expires_at if expires_at is not None else int(time.time()) + 86400
        try:
            await self._jwt_blacklist.revoke(jti, exp)  # type: ignore[attr-defined]
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
        if self._jwt_blacklist is None:  # type: ignore[attr-defined]
            return True
        try:
            from src.backend.core.auth.jwt_blacklist import RedisJwtBlacklist

            if isinstance(self._jwt_blacklist, RedisJwtBlacklist):
                await self._jwt_blacklist._redis.delete(  # type: ignore[attr-defined]
                    self._jwt_blacklist._key(jti)  # type: ignore[attr-defined]
                )
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
        if self._jwt_blacklist is None:  # type: ignore[attr-defined]
            await self.init_jwt_blacklist()
        return await self._jwt_blacklist.is_revoked(jti)  # type: ignore[attr-defined]

    async def clear_blacklist(self) -> None:
        """Очистить весь blacklist (для тестов)."""
        if self._jwt_blacklist is None:  # type: ignore[attr-defined]
            return
        try:
            from src.backend.core.auth.jwt_blacklist import RedisJwtBlacklist

            if isinstance(self._jwt_blacklist, RedisJwtBlacklist):
                pattern = f"{self._jwt_blacklist._prefix}*"
                cursor = 0
                while True:
                    cursor, keys = await self._jwt_blacklist._redis.scan(  # type: ignore[attr-defined]
                        cursor, match=pattern, count=100
                    )
                    if keys:
                        await self._jwt_blacklist._redis.delete(*keys)  # type: ignore[attr-defined]
                    if cursor == 0:
                        break
            else:
                await self._jwt_blacklist.clear()
        except Exception as exc:
            _logger.warning("JWT blacklist clear failed: %s", exc)
