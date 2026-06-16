"""Unified rate limiter — Redis-backed token bucket для всех протоколов.

Multi-instance safety: все токены в Redis (atomic INCR/EXPIRE).
Поддерживает:
- Per-API-key rate limits
- Per-IP rate limits
- Per-action rate limits
- Global fallback rate

Интегрируется в BaseEntrypoint.dispatch() и FastAPI middleware.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("RateLimitExceeded", "RedisRateLimiter", "get_rate_limiter")

logger = get_logger("entrypoints.rate_limiter")


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, *, limit: int, window: int, retry_after: int):
        super().__init__(
            f"Rate limit exceeded: {limit}/{window}s, retry after {retry_after}s"
        )
        self.limit = limit
        self.window = window
        self.retry_after = retry_after


@dataclass(slots=True)
class RateLimit:
    """Описание rate limit policy.

    Параметр ``tenant_aware`` (V19 K2 W7): когда True, к Redis-ключу
    добавляется сегмент ``tenant:<id>``, где ``<id>`` берётся из
    ``core.tenancy.current_tenant()`` (или ``_default_`` если контекст
    не установлен). Изолирует счётчики между арендаторами без изменения
    callsite'ов.
    """

    limit: int
    window_seconds: int
    key_prefix: str = "ratelimit"
    tenant_aware: bool = False


def _resolve_tenant_segment() -> str:
    """Возвращает ``tenant:<id>`` или ``tenant:_default_``.

    Изолирован в helper'е чтобы избежать import-cycle при инициализации
    модуля (``core.tenancy`` импортирует структуры из ``core.resilience``
    в фасадных re-export'ах).
    """
    try:
        from src.backend.core.tenancy import current_tenant

        ctx = current_tenant()
        if ctx is not None and ctx.tenant_id:
            return f"tenant:{ctx.tenant_id}"
    except Exception as exc:
        logger.debug("Tenant context недоступен (fallback _default_): %s", exc)
    return "tenant:_default_"


class RedisRateLimiter:
    """Token bucket rate limiter на Redis.

    Использует Redis INCR + EXPIRE (atomic). Multi-instance safe.

    Usage::

        limiter = get_rate_limiter()
        try:
            await limiter.check("api_key:abc", RateLimit(limit=100, window_seconds=60))
        except RateLimitExceeded as exc:
            return {"error": str(exc), "retry_after": exc.retry_after}
    """

    async def check(self, identifier: str, policy: RateLimit) -> dict[str, Any]:
        """Проверяет и увеличивает счётчик. Raises RateLimitExceeded при превышении.

        Returns:
            {"remaining": int, "reset_at": int, "limit": int}
        """
        try:
            from src.backend.infrastructure.clients.storage.redis import (
                get_redis_client,
            )

            redis_client = get_redis_client()
        except ImportError:
            return {"remaining": policy.limit, "reset_at": 0, "limit": policy.limit}

        now = int(time.time())
        window_start = now - (now % policy.window_seconds)
        if policy.tenant_aware:
            tenant_seg = _resolve_tenant_segment()
            key = f"{policy.key_prefix}:{tenant_seg}:{identifier}:{window_start}"
        else:
            key = f"{policy.key_prefix}:{identifier}:{window_start}"

        try:
            raw = getattr(redis_client, "_raw_client", None) or redis_client
            pipe = raw.pipeline() if hasattr(raw, "pipeline") else None
            if pipe is not None:
                pipe.incr(key)
                pipe.expire(key, policy.window_seconds)
                results = await pipe.execute()
                count = int(results[0]) if results else 0
            else:
                count = await raw.incr(key)
                await raw.expire(key, policy.window_seconds)
        except Exception as exc:
            logger.warning("Rate limiter Redis failed (fail-open): %s", exc)
            return {"remaining": policy.limit, "reset_at": 0, "limit": policy.limit}

        reset_at = window_start + policy.window_seconds
        remaining = max(0, policy.limit - count)

        if count > policy.limit:
            raise RateLimitExceeded(
                limit=policy.limit,
                window=policy.window_seconds,
                retry_after=reset_at - now,
            )

        return {"remaining": remaining, "reset_at": reset_at, "limit": policy.limit}


_instance: RedisRateLimiter | None = None


def get_rate_limiter() -> RedisRateLimiter:
    global _instance
    if _instance is None:
        _instance = RedisRateLimiter()
    return _instance
