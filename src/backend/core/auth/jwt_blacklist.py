"""Redis blacklist для отозванных JWT (по ``jti`` и batch по ``iat``).

V7 R1 — отзыв токенов до истечения срока ``exp``. Используется при
logout, compromised-key rotation, force-logout по требованию админа.

S18 W4 (S-L8-5) — batch-revocation при JWKS rotation: один атомарный
вызов :meth:`RedisJwtBlacklist.revoke_before_time` делает невалидными
все ранее выданные токены (по ``iat``) без необходимости знать их
``jti``-список. Соответствующая проверка :meth:`is_iat_revoked`
вызывается из :class:`JwtBackend.decode` независимо от per-``jti``
gate.

Ключи Redis:
* ``blacklist:jwt:<jti>`` → ``1`` с TTL = (exp - now) секунд (per-token).
* ``blacklist:jwt:revoke_before`` → unix-timestamp (без TTL, global
  rotation barrier). Multi-tenant вариант (per-tenant prefix) — carryover
  S19+ (см. KNOWN_ISSUES.md).

Wave [s2/k1-2-jwt-jwks] + [wave:s18/k1-w4-jwt-blacklist-batch-revoke].
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

__all__ = ("RedisJwtBlacklist", "JwtBlacklistProtocol")

_logger = logging.getLogger(__name__)


class JwtBlacklistProtocol(Protocol):
    """Контракт blacklist'а: per-jti revoke + batch revoke-before.

    Notes:
        :meth:`revoke_before_time` и :meth:`is_iat_revoked` — расширение
        S18 W4. В :class:`JwtBackend.decode` вызов :meth:`is_iat_revoked`
        защищён ``hasattr``-guard для backward-compat с реализациями,
        которые ещё не реализуют batch-revoke.
    """

    async def is_revoked(self, jti: str) -> bool: ...

    async def revoke(self, jti: str, expires_at: int) -> None: ...

    async def revoke_before_time(self, time_threshold: int) -> None: ...

    async def is_iat_revoked(self, iat: int | None) -> bool: ...


class RedisJwtBlacklist:
    """Blacklist отозванных JWT поверх Redis (per-jti + batch revoke-before).

    Args:
        redis: redis.asyncio.Redis клиент (или совместимый proxy).
        key_prefix: Префикс ключей (по умолчанию ``blacklist:jwt:``).
    """

    _REVOKE_BEFORE_SUFFIX = "revoke_before"

    def __init__(self, redis: Any, *, key_prefix: str = "blacklist:jwt:") -> None:
        self._redis = redis
        self._prefix = key_prefix

    def _key(self, jti: str) -> str:
        return f"{self._prefix}{jti}"

    def _revoke_before_key(self) -> str:
        return f"{self._prefix}{self._REVOKE_BEFORE_SUFFIX}"

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

    async def revoke_before_time(self, time_threshold: int) -> None:
        """Batch-отзыв всех токенов, выданных до ``time_threshold`` (S18 W4).

        Сохраняет global timestamp в Redis под ключом
        ``<prefix>revoke_before``. Все последующие :meth:`is_iat_revoked`
        проверяют ``iat`` против этого барьера.

        Args:
            time_threshold: Unix timestamp; токены с ``iat < threshold``
                становятся невалидными.

        Notes:
            * Без TTL — barrier хранится бессрочно (или до явного reset).
            * Идемпотентен: повторный вызов с большим threshold перезаписывает,
              с меньшим — fail-closed (advisor pt 3): новый threshold всегда
              применяется как ``MAX(current, new)`` чтобы избежать accidental
              rotation rollback.
        """
        try:
            current_raw = await self._redis.get(self._revoke_before_key())
            current = int(current_raw) if current_raw is not None else 0
            new_value = max(current, int(time_threshold))
            await self._redis.set(self._revoke_before_key(), str(new_value).encode())
        except Exception as exc:
            _logger.error(
                "JWT blacklist revoke_before_time(%s) failed: %s", time_threshold, exc
            )
            raise

    async def is_iat_revoked(self, iat: int | None) -> bool:
        """Проверяет, попадает ли токен под batch-revoke по ``iat`` (S18 W4).

        Args:
            iat: ``iat``-claim токена (unix timestamp) или ``None``.

        Returns:
            * ``False`` если ``iat is None`` (нет данных — не блокируем,
              иначе custom JWT без iat станут невалидными);
            * ``False`` при отсутствии barrier в Redis;
            * ``True`` если ``int(iat) < stored_threshold``;
            * ``False`` в любом другом случае (включая ошибки Redis —
              fail-open для backward-compat с per-jti path; security
              compensation: per-jti gate всё равно срабатывает).
        """
        if iat is None:
            return False
        try:
            iat_int = int(iat)
        except (TypeError, ValueError):
            _logger.warning(
                "JWT blacklist is_iat_revoked: некорректный iat=%r — skip", iat
            )
            return False
        try:
            value = await self._redis.get(self._revoke_before_key())
        except Exception as exc:
            _logger.warning("JWT blacklist GET revoke_before failed: %s", exc)
            return False
        if value is None:
            return False
        try:
            threshold = int(value)
        except (TypeError, ValueError):
            return False
        return iat_int < threshold
