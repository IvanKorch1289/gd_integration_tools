"""Rate-limit зависимость для FastAPI-роутов (Sprint 0 #12 → Sprint 1 cleanup).

В ``fastapi-limiter==0.2.0`` backend — ``pyrate_limiter.Limiter``,
``FastAPILimiter.init`` упразднён. Лимит применяется per-route через
``Depends(get_default_rate_limiter())``. Identifier и callback —
общие из ``core.decorators.limiting_callbacks``.

Файл лежит в ``middlewares/`` исторически (Sprint 0 #12 ASGI-bootstrap),
после миграции на per-route Depends это уже не middleware; перенос в
``entrypoints/dependencies/`` запланирован отдельным cleanup.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi_limiter.depends import RateLimiter as RateLimitDependency
from fastapi_limiter.depends import WebSocketRateLimiter
from pyrate_limiter import Duration, Limiter, Rate

from src.backend.core.config.security import secure_settings
from src.backend.core.decorators.limiting_callbacks import (
    default_callback,
    default_identifier,
)

__all__ = (
    "RateLimitDependency",
    "WebSocketRateLimiter",
    "get_default_limiter",
    "get_default_rate_limiter",
)


@lru_cache(maxsize=1)
def get_default_limiter() -> Limiter:
    """Singleton ``pyrate_limiter.Limiter`` по конфигу ``secure_settings``."""
    rate = Rate(
        secure_settings.rate_limit,
        Duration.SECOND * secure_settings.rate_time_measure_seconds,
    )
    return Limiter(rate)


@lru_cache(maxsize=1)
def get_default_rate_limiter() -> RateLimitDependency:
    """Singleton ``RateLimiter``-зависимость с дефолтными identifier/callback.

    Кэшируется, чтобы все ``Depends(get_default_rate_limiter())`` ссылались
    на один объект — FastAPI дедуплицирует одинаковые зависимости в графе
    запроса, а ``pyrate_limiter`` не плодит лишних bucket-key слотов.

    ``blocking=False`` — превышение лимита моментально возвращает 429
    через ``default_callback``, в отличие от блокирующего ожидания.
    """
    return RateLimitDependency(
        limiter=get_default_limiter(),
        identifier=default_identifier,
        callback=default_callback,
        blocking=False,
    )
