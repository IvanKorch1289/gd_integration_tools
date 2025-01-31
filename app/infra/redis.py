from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import asyncio
from aioredis import Redis, RedisError, create_redis_pool

from app.config.settings import RedisSettings, settings
from app.utils.decorators import singleton
from app.utils.logging import db_logger


__all__ = ("redis_client",)


@singleton
class RedisClient:
    """Manages Redis connection pool with asynchronous operations support.

    Provides safe connection creation/closing, health checks,
    and automatic connection recovery.

    Attributes:
        _pool (Optional[Redis]): Main connection pool
        _lock (asyncio.Lock): Lock for pool initialization synchronization
        settings (RedisSettings): Connection configuration parameters
    """

    def __init__(self, settings: RedisSettings):
        """Initializes the client with specified connection settings.

        Args:
            settings (RedisSettings): Redis connection configuration containing:
                - redis_host: Redis host
                - redis_port: Redis port
                - redis_db_cache: Database number
                - redis_pass: Password (optional)
                - redis_encoding: Data encoding
                - redis_timeout: Connection timeout
                - redis_pool_minsize: Minimum pool size
                - redis_use_ssl: Use SSL connection
        """
        self._pool: Optional[Redis] = None
        self._lock = asyncio.Lock()
        self.settings = settings

    async def _ensure_pool(self) -> None:
        """Creates or updates the connection pool if needed.

        Ensures thread-safe pool initialization using a lock.

        Raises:
            RedisError: If connection establishment fails
        """
        if self._pool is None or self._pool.closed:
            async with self._lock:
                if self._pool is None or self._pool.closed:
                    try:
                        protocol = (
                            "rediss"
                            if self.settings.redis_use_ssl
                            else "redis"
                        )
                        address = (
                            f"{protocol}://{self.settings.redis_host}:"
                            f"{self.settings.redis_port}"
                        )

                        self._pool = await create_redis_pool(
                            address=address,
                            db=self.settings.redis_db_cache,
                            password=self.settings.redis_pass,
                            encoding=self.settings.redis_encoding,
                            timeout=self.settings.redis_timeout,
                            minsize=self.settings.redis_pool_minsize,
                            ssl=self.settings.redis_use_ssl,
                        )
                        db_logger.info("Redis connection pool initialized")
                    except Exception as e:
                        db_logger.error(f"Redis connection failed: {str(e)}")
                        raise RedisError(f"Connection error: {str(e)}") from e

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[Redis]:
        """Provides asynchronous context manager for Redis connections.

        Usage example:
            async with redis_client.connection() as conn:
                await conn.set("key", "value")

        Yields:
            Redis: Active Redis connection

        Raises:
            RedisError: For connection-related issues
        """
        await self._ensure_pool()
        try:
            yield self._pool
        except RedisError as e:
            db_logger.error(f"Redis operation failed: {str(e)}")
            await self.close()
            raise
        except Exception as e:
            db_logger.error(f"Unexpected error: {str(e)}")
            await self.close()
            raise RedisError("Connection terminated") from e

    async def close(self) -> None:
        """Properly closes all connections and releases resources.

        Should be called during application shutdown.
        """
        if self._pool and not self._pool.closed:
            try:
                self._pool.close()
                await self._pool.wait_closed()
                db_logger.info("Redis connections closed")
            except Exception as e:
                db_logger.error(f"Error closing connections: {str(e)}")
            finally:
                self._pool = None

    async def check_connection(self) -> bool:
        """Verifies Redis connection health.

        Returns:
            bool: True if connection is active, False on errors

        Usage example:
            if await redis_client.check_connection():
                print("Connected to Redis")
        """
        try:
            async with self.connection() as conn:
                return await conn.ping()
        except RedisError:
            return False

    async def dispose(self) -> None:
        """Alias for close(). Intended for explicit termination."""
        await self.close()


# Client initialization with settings
redis_client = RedisClient(settings=settings.redis)
