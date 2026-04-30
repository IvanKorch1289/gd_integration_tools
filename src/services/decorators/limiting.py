"""Rate-limit декоратор для FastAPI-роутов (services-слой, W6 cleanup).

Декоратор не зависит от ``infrastructure/`` напрямую — он использует
callbacks из ``core/decorators/limiting_callbacks`` и внешний пакет
``fastapi_limiter``. Сам ``init_limiter`` (привязка к redis) остаётся
в ``infrastructure/``.
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable

from fastapi import HTTPException, Request, Response, status

from src.core.config.settings import settings
from src.core.decorators.limiting_callbacks import default_callback, default_identifier

__all__ = (
    "RouteLimiter",
    "default_callback",
    "default_identifier",
    "route_limiting",
)


logger = logging.getLogger("services.decorators.limiting")


class RouteLimiter:
    """Декоратор rate-limit FastAPI-маршрутов.

    Делегирует работу ``fastapi_limiter.depends.RateLimiter``, который
    обращается к Redis через ``FastAPILimiter``, инициализированный
    ``infrastructure.decorators.limiting.init_limiter``.
    """

    def __init__(
        self,
        times: int = settings.secure.rate_limit,
        seconds: int = settings.secure.rate_time_measure_seconds,
        fail_open: bool = False,
    ) -> None:
        self.times = times
        self.seconds = seconds
        self.fail_open = fail_open

    def __call__(self, func: Callable[..., Any]) -> Callable[..., Any]:
        from fastapi_limiter.depends import RateLimiter

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = kwargs.get("request")
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if request is None:
                raise RuntimeError("Request object not found")

            limiter = RateLimiter(
                times=self.times,
                seconds=self.seconds,
                identifier=default_identifier,
                callback=default_callback,
            )

            try:
                response = Response()
                await limiter(request, response)
            except HTTPException:
                raise
            except Exception as exc:
                logger.error("Rate limiter error: %s", str(exc), exc_info=True)
                if not self.fail_open:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Rate limiter unavailable",
                    ) from exc

            return await func(*args, **kwargs)

        return wrapper


route_limiting = RouteLimiter()
