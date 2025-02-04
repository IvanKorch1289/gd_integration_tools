from contextlib import asynccontextmanager
from functools import wraps
from typing import AsyncIterator, Optional

import asyncio
from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from app.config.settings import RedisSettings, settings
from app.utils.decorators.singleton import singleton
from app.utils.logging_service import redis_logger


__all__ = ("redis_client", "RedisClient")


@singleton
class RedisClient:
    def __init__(self, settings: RedisSettings):
        self._client: Optional[Redis] = None
        self._lock = asyncio.Lock()
        self.settings = settings
        self._connection_pool: Optional[ConnectionPool] = None

    async def _init_pool(self) -> None:
        redis_url = (
            f"rediss://{self.settings.rhost}:{self.settings.port}"
            if self.settings.use_ssl
            else f"redis://{self.settings.host}:{self.settings.port}"
        )

        self._connection_pool = ConnectionPool.from_url(
            redis_url,
            db=self.settings.db_cache,
            password=self.settings.password or None,
            encoding=self.settings.encoding,
            socket_timeout=self.settings.timeout,
            socket_connect_timeout=self.settings.connect_timeout,
            socket_keepalive=self.settings.redis_keepalive,
            retry_on_timeout=self.settings.retry_on_timeout,
            max_connections=self.settings.max_connections,
            decode_responses=False,
        )

        self._client = Redis(connection_pool=self._connection_pool)
        redis_logger.info("Redis connection pool initialized")

    async def _ensure_connected(self) -> None:
        async with self._lock:
            if not self._client or not await self._client.ping():
                await self._init_pool()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[Redis]:
        await self._ensure_connected()
        try:
            yield self._client
        except RedisError as exc:
            redis_logger.error(f"Redis error: {str(exc)}")
            await self.close()
            raise
        finally:
            # Не закрываем соединение здесь - пулом управляет ConnectionPool
            pass

    async def close(self) -> None:
        if self._connection_pool:
            try:
                await self._connection_pool.disconnect()
                redis_logger.info("Redis connections closed")
            except Exception as e:
                redis_logger.error(f"Close error: {str(e)}")
            finally:
                self._client = None
                self._connection_pool = None

    async def check_connection(self) -> bool:
        try:
            async with self.connection() as conn:
                return await conn.ping()
        except RedisError:
            return False

    def reconnect_on_failure(self, func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            try:
                return await func(self, *args, **kwargs)
            except (ConnectionError, TimeoutError):
                redis_logger.warning("Reconnecting to Redis...")
                await self.close()
                await self._ensure_connected()
                return await func(self, *args, **kwargs)

        return wrapper

    async def __aenter__(self) -> "RedisClient":
        await self._ensure_connected()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()


redis_client = RedisClient(settings=settings.redis)
