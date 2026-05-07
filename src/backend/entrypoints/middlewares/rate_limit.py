"""Rate-limit middleware (Sprint 0 #12).

Тонкая обёртка над ``fastapi-limiter`` (route-level Depends).

Текущая версия ``fastapi-limiter==0.1.6`` использует ``pyrate_limiter.Limiter``
как backend и не предоставляет глобальной инициализации (FastAPILimiter.init
из старых версий упразднён). Лимит применяется per-route через ``Depends``.

Пример:
    from fastapi_limiter.depends import RateLimiter
    from pyrate_limiter import Duration, Limiter, Rate

    rate = Rate(10, Duration.SECOND)
    limiter = Limiter(rate)
    app.add_route("/api/x", deps=[Depends(RateLimiter(limiter))], ...)
"""

from __future__ import annotations

from fastapi_limiter.depends import RateLimiter as RateLimitDependency
from fastapi_limiter.depends import WebSocketRateLimiter

__all__ = ("RateLimitDependency", "WebSocketRateLimiter")
