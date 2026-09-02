"""Redis-backed implementations for mobile JWT Phase 2 protections.

S47 W1 (ADR-0265 §2): production-grade multi-pod safe stores.

Modules:
- RedisRevocationStore: per-jti revocation with TTL = (exp - now)
- RedisRateLimiter: per-device fixed-window rate limiting

Both use ``get_redis_client()`` from ``core.storage.redis`` for DI-safe
access. Graceful no-op when Redis is unavailable (returns False / allows
request — caller decides fail-open vs fail-closed).

Production deployment:
- ENABLE Redis: set ``REDIS_ENABLED=true`` in env, ``REDIS_URL=redis://...``
- Multi-pod: each pod shares Redis state, so revocation + rate limit
  are cluster-wide consistent.
"""

from __future__ import annotations

import time
from typing import Any

from src.backend.core.auth.jwt_backend import JwtVerificationError
from src.backend.core.logging import get_logger

_logger = get_logger(__name__)


def _is_fail_closed() -> bool:
    """Read ``mobile_jwt_revoc_fail_closed`` from feature_flags (lazy).

    S49 M1-#2: production default True → fail-CLOSED на Redis outage.
    Override через env FEATURE_MOBILE_JWT_REVOC_FAIL_CLOSED=false для
    dev/test без Redis (legacy fail-OPEN behavior).
    """
    try:
        from src.backend.core.config.features import feature_flags

        return bool(getattr(feature_flags, "mobile_jwt_revoc_fail_closed", True))
    except Exception as exc:
        # Settings недоступны (early boot / test) → fail-CLOSED default.
        _logger.warning(
            "feature_flags.mobile_jwt_revoc_fail_closed unavailable err=%s — "
            "fail-CLOSED default applied",
            exc,
        )
        return True


def _emit_revocation_fail_open_audit(reason: str) -> None:
    """Helper: audit-event для mobile_jwt revocation fail-OPEN (W11).

    S48 W11 swarm audit (A9 Security #2): revocation check возвращает
    False при недоступности Redis → отозванный JWT считается валидным.
    Production deployment теряет revocation guarantee без observability.

    Lazy import (избегаем circular с core.audit).
    """
    try:
        from src.backend.core.audit.facade._base import emit_audit_safe

        emit_audit_safe(
            event="security.auth.revocation_fail_open",
            action="redis_revocation_check",
            outcome="failure",
            severity="error",
            extra={
                "reason": reason,
                "warning": (
                    "Mobile JWT revocation check returned False due to "
                    "Redis unavailability. Revoked JWT may be accepted. "
                    "Set FEATURE_MOBILE_JWT_REVOC_FAIL_CLOSED=true for "
                    "fail-CLOSED behavior (Sprint 49 default)."
                ),
            },
        )
    except Exception as exc:
        _logger.warning(
            "Failed to emit revocation_fail_open audit (reason=%s): %s",
            reason,
            exc,
        )


def _emit_revocation_fail_closed_audit(reason: str) -> None:
    """Helper: audit-event для mobile_jwt revocation fail-CLOSED (S49 M1-#2).

    Production deployment с mobile_jwt_revoc_fail_closed=True теперь
    reject'ит token при Redis outage. Caller (MobileJwtVerifier) получает
    JwtVerificationError → reject. Security team видит alert в audit.
    """
    try:
        from src.backend.core.audit.facade._base import emit_audit_safe

        emit_audit_safe(
            event="security.auth.revocation_fail_closed",
            action="redis_revocation_check",
            outcome="denied",
            severity="warning",
            extra={
                "reason": reason,
                "behavior": "fail_closed_enforced",
                "info": (
                    "Mobile JWT revocation check raised JwtVerificationError "
                    "due to Redis unavailability. Revoked JWT rejected "
                    "(production-safe behavior)."
                ),
            },
        )
    except Exception as exc:
        _logger.warning(
            "Failed to emit revocation_fail_closed audit (reason=%s): %s",
            reason,
            exc,
        )


class RedisRevocationStore:
    """Redis-backed implementation of RevocationStore.

    Key format: ``gd:mobile:revoked:<jti>``
    Value: revoked_at timestamp (unix seconds)
    TTL: ``max(1, int(expires_at - now))`` seconds

    Args:
        key_prefix: Redis key prefix (default: ``gd:mobile:revoked:``).
            Allows namespacing per environment / tenant.
    """

    def __init__(self, *, key_prefix: str = "gd:mobile:revoked:") -> None:
        self._prefix = key_prefix

    def _key(self, jti: str) -> str:
        return f"{self._prefix}{jti}"

    async def _get_client(self) -> Any:
        """Lazy-fetch Redis client. Returns None if Redis unavailable.

        ``get_redis_client()`` is a SYNC factory returning RedisClient directly
        (no await). We keep this method async for API symmetry with other
        stores; the await is intentionally absent.
        """
        try:
            from src.backend.core.storage.redis import get_redis_client

            return get_redis_client()
        except Exception as exc:
            _logger.warning(
                "redis revocation store: client unavailable: %s", exc
            )
            return None

    async def is_revoked(self, jti: str) -> bool:
        """Check if a JWT ID has been revoked.

        Returns False on Redis errors (fail-open). Caller should treat
        this as best-effort and may override with fail-closed policy.

        S48 W11 swarm audit (A9 Security #2 / A1 Core #1): fail-OPEN
        silent без observability → отозванный JWT считается валидным
        при недоступности Redis. Production deployment теряет revocation
        гарантию.

        S49 M1-#2: добавлен fail-CLOSED через feature flag
        ``mobile_jwt_revoc_fail_closed`` (default=True). При Redis outage
        + flag=True → raise JwtVerificationError вместо False.
        Caller (MobileJwtVerifier) получает исключение и reject'ит token.
        Fail-OPEN остаётся только при explicit flag=False (legacy dev/test).
        """
        client = await self._get_client()
        if client is None:
            if _is_fail_closed():
                _emit_revocation_fail_closed_audit("redis_unavailable")
                raise JwtVerificationError(
                    "JWT revocation store unavailable (fail-CLOSED enforced)"
                )
            _emit_revocation_fail_open_audit("redis_unavailable")
            return False  # fail-open
        try:
            value = await client.cache_get(self._key(jti))
            return value is not None
        except Exception as exc:
            _logger.warning(
                "redis revocation is_revoked error: jti=%s err=%s", jti, exc
            )
            if _is_fail_closed():
                _emit_revocation_fail_closed_audit(
                    f"redis_error:{type(exc).__name__}"
                )
                raise JwtVerificationError(
                    "JWT revocation check failed (fail-CLOSED enforced)"
                ) from exc
            _emit_revocation_fail_open_audit(f"redis_error:{type(exc).__name__}")
            return False  # fail-open

    async def revoke(self, jti: str, *, expires_at: float) -> None:
        """Revoke a JWT ID. ``expires_at`` = when the token would have expired.

        TTL is set to (expires_at - now) so the revocation entry auto-expires
        when the token itself would have expired (no manual cleanup needed).
        """
        if not jti or not isinstance(jti, str):
            raise ValueError("jti must be non-empty string")
        if expires_at <= time.time():
            raise ValueError("expires_at must be in the future")

        client = await self._get_client()
        if client is None:
            _logger.warning(
                "redis revocation revoke: client unavailable, jti=%s not persisted",
                jti,
            )
            return

        ttl = max(1, int(expires_at - time.time()))
        try:
            await client.cache_set(
                self._key(jti), str(int(time.time())), expire=ttl
            )
            _logger.info(
                "redis revocation revoke: jti=%s ttl=%d", jti, ttl
            )
        except Exception as exc:
            _logger.error(
                "redis revocation revoke failed: jti=%s err=%s", jti, exc
            )
            raise

    async def cleanup_expired(self) -> int:
        """TTL handles cleanup automatically. Returns 0 (no-op for Redis impl)."""
        # Redis TTL auto-removes keys; explicit cleanup is unnecessary.
        return 0


class RedisRateLimiter:
    """Redis-backed per-device fixed-window rate limiter.

    Algorithm: fixed window with INCR + EXPIRE.
    Key: ``gd:mobile:rl:<device_id>:<window_floor>``
    Window: ``floor(now / window_seconds) * window_seconds``
    On request:
        count = INCR(key)
        if count == 1: EXPIRE(key, window_seconds)
        if count > max_requests: reject

    Trade-off vs sliding window: simpler, fewer Redis ops per request,
    but allows 2x burst at window boundaries. Acceptable for mobile
    auth brute-force protection (not strict SLA).

    Args:
        max_requests: Max requests per window.
        window_seconds: Window duration in seconds.
        key_prefix: Redis key prefix (default: ``gd:mobile:rl:``).
    """

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: float,
        key_prefix: str = "gd:mobile:rl:",
    ) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be > 0")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self._max = max_requests
        self._window = int(window_seconds)
        self._prefix = key_prefix

    def _key(self, device_id: str, window_start: int) -> str:
        return f"{self._prefix}{device_id}:{window_start}"

    async def _get_client(self) -> Any:
        try:
            from src.backend.core.storage.redis import get_redis_client

            # get_redis_client() is sync (returns RedisClient directly).
            return get_redis_client()
        except Exception as exc:
            _logger.warning("redis rate limiter: client unavailable: %s", exc)
            return None

    async def check(self, device_id: str) -> tuple[bool, int]:
        """Check if device is within rate limit.

        Returns:
            (allowed, remaining). On Redis error, allows request (fail-open).

        """
        if not device_id:
            raise ValueError("device_id must be non-empty")

        client = await self._get_client()
        if client is None:
            # Fail-open when Redis unavailable. Caller should log this
            # event for monitoring (e.g., high failure rate = degraded RL).
            return (True, self._max)

        window_start = int(time.time()) // self._window * self._window
        key = self._key(device_id, window_start)

        try:
            count_raw = await client.cache_get(key)
            count = int(count_raw) if count_raw else 0
            count += 1
            await client.cache_set(key, str(count), expire=self._window)
            if count > self._max:
                return (False, 0)
            return (True, self._max - count)
        except Exception as exc:
            _logger.warning(
                "redis rate limit check error: device=%s err=%s", device_id, exc
            )
            return (True, self._max)  # fail-open
