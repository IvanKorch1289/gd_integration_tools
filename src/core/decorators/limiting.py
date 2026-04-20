from functools import wraps
from typing import Any, Callable

from fastapi import HTTPException, Request, Response, status

from app.core.config.settings import settings
from app.infrastructure.clients.storage.redis import redis_client
from app.infrastructure.external_apis.logging_service import app_logger

__all__ = ("init_limiter", "route_limiting", "RouteLimiter")


async def default_identifier(request: Request) -> str:
    user = getattr(request, "user", None)
    if user and getattr(user, "id", None):
        return f"user:{user.id}"

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"

    return f"ip:{client_ip}:{request.url.path}"


async def default_callback(request: Request, response: Response, pexpire: int) -> None:
    retry_after = max(1, pexpire // 1000)
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded",
        headers={"Retry-After": str(retry_after)},
    )


async def init_limiter() -> None:
    import redis.asyncio as redis
    from fastapi_limiter import FastAPILimiter

    try:
        limits_client = await redis_client.limits_client()
        connection = redis.Redis(
            connection_pool=limits_client.connection_pool,
            encoding="utf-8",
            decode_responses=True,
        )
        await FastAPILimiter.init(
            connection, identifier=default_identifier, http_callback=default_callback
        )
        app_logger.info("FastAPILimiter initialized")
    except Exception as exc:
        app_logger.error(
            "Error initializing FastAPILimiter: %s", str(exc), exc_info=True
        )
        raise


class RouteLimiter:
    """Декоратор для rate limiting FastAPI-маршрутов через Redis."""

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
                app_logger.error("Rate limiter error: %s", str(exc), exc_info=True)
                if not self.fail_open:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Rate limiter unavailable",
                    ) from exc

            return await func(*args, **kwargs)

        return wrapper


route_limiting = RouteLimiter()
