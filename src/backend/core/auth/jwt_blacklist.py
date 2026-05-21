"""Redis blacklist для отозванных JWT (по ``jti``).

V7 R1 — отзыв токенов до истечения срока ``exp``. Используется при
logout, compromised-key rotation, force-logout по требованию админа.

Ключи:
* ``blacklist:jwt:<jti>`` → ``1`` с TTL = (exp - now) секунд.

Wave [s2/k1-2-jwt-jwks].
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

__all__ = ("RedisJwtBlacklist", "JwtBlacklistProtocol")

_logger = logging.getLogger(__name__)


class JwtBlacklistProtocol(Protocol):
    """Контракт blacklist'а: ``is_revoked`` + ``revoke``."""

    async def is_revoked(self, jti: str) -> bool: ...

    async def revoke(self, jti: str, expires_at: int) -> None: ...


class RedisJwtBlacklist:
    """Blacklist отозванных JWT поверх Redis.

    Args:
        redis: redis.asyncio.Redis клиент (или совместимый proxy).
        key_prefix: Префикс ключей (по умолчанию ``blacklist:jwt:``).
    """

    def __init__(self, redis: Any, *, key_prefix: str = "blacklist:jwt:") -> None:
        self._redis = redis
        self._prefix = key_prefix

    def _key(self, jti: str) -> str:
        return f"{self._prefix}{jti}"

    async def is_revoked(self, jti: str) -> bool:
        """Проверяет, отозван ли токен по его ``jti``."""
        try:
            value = await self._redis.get(self._key(jti))
        except Exception as exc:
            _logger.warning("JWT blacklist GET failed for jti=%s: %s", jti, exc)
            return False
        return value is not None

    async def revoke(self, jti: str, expires_at: int) -> None:
        """Отзывает токен до timestamp ``expires_at`` (unix epoch).

        Если токен уже истёк — no-op (TTL <= 0).
        """
        ttl = max(int(expires_at - time.time()), 0)
        if ttl <= 0:
            return
        try:
            await self._redis.set(self._key(jti), b"1", ex=ttl)
        except Exception as exc:
            _logger.error("JWT blacklist SET failed for jti=%s: %s", jti, exc)
            raise
