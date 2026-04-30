"""Инициализация ``fastapi_limiter`` (W6: декоратор переехал в services).

В этом модуле остаётся только ``init_limiter`` — он связывает
``FastAPILimiter`` с конкретным redis-клиентом из ``infrastructure``.
Сами декораторы (``route_limiting``, ``RouteLimiter``) — в
``src/services/decorators/limiting.py``; общие callbacks
(``default_identifier``, ``default_callback``) — в
``src/core/decorators/limiting_callbacks.py``.
"""

from __future__ import annotations

from src.core.decorators.limiting_callbacks import default_callback, default_identifier
from src.infrastructure.clients.storage.redis import redis_client
from src.infrastructure.external_apis.logging_service import app_logger

__all__ = ("init_limiter",)


async def init_limiter() -> None:
    """Инициализирует ``FastAPILimiter`` с redis-клиентом для rate-limit."""
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
