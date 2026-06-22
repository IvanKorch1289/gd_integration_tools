"""Rate-limit зависимость для FastAPI-роутов.

В ``fastapi-limiter==0.2.0`` backend — ``RedisLimiterAdapter`` (multi-instance safe),
``FastAPILimiter.init`` упразднён. Лимит применяется per-route через
``Depends(get_default_rate_limiter())``. Identifier и callback — общие из
``core.decorators.limiting_callbacks``.

S168 W11 P1-3: миграция с ``pyrate_limiter.Limiter`` (in-memory, per-process)
на ``unified_rate_limiter.RedisRateLimiter`` (multi-instance via Redis).
Ponytail minimum: ``RedisLimiterAdapter`` реализует только ``try_acquire_async``
для совместимости с ``fastapi_limiter.depends.RateLimiter``. ``get_rate_limiter``
fail-open при недоступности Redis (как в ``webhook/handler.py``).

Расположение в ``entrypoints/dependencies/`` отражает суть API:
это ``Depends``-объект, не ASGI-middleware. Sprint 1 V16 cleanup
перенёс файл из ``entrypoints/middlewares/``.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi_limiter.depends import RateLimiter as RateLimitDependency
from fastapi_limiter.depends import WebSocketRateLimiter

from src.backend.core.config.security import secure_settings
from src.backend.core.decorators.limiting_callbacks import (
    default_callback,
    default_identifier,
)
from src.backend.services.resilience.rate_limiter import (
    RateLimit,
    RateLimitExceeded,
    get_rate_limiter,
)

__all__ = (
    "RateLimitDependency",
    "WebSocketRateLimiter",
    "RedisLimiterAdapter",
    "get_default_limiter",
    "get_default_rate_limiter",
)


class RedisLimiterAdapter:
    """Adapter: ``pyrate_limiter.Limiter`` interface → ``RedisRateLimiter`` backend.

    Multi-instance safe via Redis (atomic INCR/EXPIRE). Совместим с
    ``fastapi_limiter.depends.RateLimiter``, который вызывает только
    ``limiter.try_acquire_async(key, blocking=...)``.

    Args:
        rate_limit: Maximum permits per window.
        window_seconds: Window duration in seconds.
    """

    def __init__(self, *, rate_limit: int, window_seconds: int) -> None:
        self._limiter = get_rate_limiter()
        self._rate_limit = rate_limit
        self._window_seconds = window_seconds

    async def try_acquire_async(
        self,
        name: str = "pyrate",
        weight: int = 1,
        blocking: bool = True,
        timeout: int | float = -1,
    ) -> bool:
        """Acquire `weight` permits from bucket `name`. Multi-instance via Redis.

        Returns:
            True if permits acquired, False if rate limit exceeded.
        """
        # Map pyrate_limiter semantics → RedisRateLimiter.check()
        # window: timeout > 0 используем timeout, иначе configured window
        if timeout is None or timeout < 0:
            window = self._window_seconds
        else:
            window = max(1, int(timeout))
        try:
            await self._limiter.check(
                name,
                RateLimit(
                    limit=weight,
                    window_seconds=window,
                    key_prefix="pyrate",
                ),
            )
        except RateLimitExceeded:
            return False
        return True

    @property
    def rate_limit(self) -> int:
        """Configured rate limit (permits per window)."""
        return self._rate_limit

    @property
    def window_seconds(self) -> int:
        """Configured window in seconds."""
        return self._window_seconds


@lru_cache(maxsize=1)
def get_default_limiter() -> RedisLimiterAdapter:
    """Singleton ``RedisLimiterAdapter`` по конфигу ``secure_settings``.

    S168 W11 P1-3: Redis-backed (multi-instance safe). Pyrate_limiter был
    in-memory (per-process), что давало N×configured rate limit при N replicas.
    """
    return RedisLimiterAdapter(
        rate_limit=secure_settings.rate_limit,
        window_seconds=secure_settings.rate_time_measure_seconds,
    )


@lru_cache(maxsize=1)
def get_default_rate_limiter() -> RateLimitDependency:
    """Singleton ``RateLimiter``-зависимость с дефолтными identifier/callback.

    Кэшируется, чтобы все ``Depends(get_default_rate_limiter())`` ссылались
    на один объект — FastAPI дедуплицирует одинаковые зависимости в графе
    запроса.

    ``blocking=False`` — превышение лимита моментально возвращает 429
    через ``default_callback``, в отличие от блокирующего ожидания.
    """
    return RateLimitDependency(
        limiter=get_default_limiter(),  # type: ignore[arg-type]  # RedisLimiterAdapter matches Limiter protocol (try_acquire_async)
        identifier=default_identifier,
        callback=default_callback,
        blocking=False,
    )
