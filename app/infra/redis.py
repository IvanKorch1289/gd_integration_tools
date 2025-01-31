from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import asyncio
from aioredis import Redis, RedisError, create_redis_pool

from app.config.settings import RedisSettings, settings


__all__ = ("redis_client",)


class RedisClient:
    """
    Класс для управления пулом соединений с Redis.

    Attributes:
        _pool (Optional[Redis]): Пул соединений с Redis
        _lock (asyncio.Lock): Блокировка для синхронизации создания пула
        settings (RedisSettings): Конфигурация подключения к Redis
    """

    def __init__(self, settings: RedisSettings):
        """
        Инициализация клиента с настройками подключения

        Args:
            settings: Объект с параметрами подключения к Redis
        """
        self._pool: Optional[Redis] = None
        self._lock = asyncio.Lock()
        self.settings = settings

    async def _ensure_pool(self) -> None:
        """Создает пул соединений при первом обращении"""
        if self._pool is None or self._pool.closed:
            async with self._lock:
                # Повторная проверка после захвата блокировки
                if self._pool is None or self._pool.closed:
                    address = (
                        f"redis://{self.settings.redis_host}:{self.settings.redis_port}"
                    )
                    self._pool = await create_redis_pool(
                        address=address,
                        db=self.settings.redis_db_cache,
                        # password=self.settings.redis_pass,
                        encoding=self.settings.redis_encoding,
                        timeout=self.settings.redis_timeout,
                        minsize=self.settings.redis_pool_minsize,
                        ssl=self.settings.redis_use_ssl,
                    )

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[Redis]:
        """Контекстный менеджер для работы с соединением"""
        await self._ensure_pool()
        try:
            yield self._pool
        except RedisError:
            await self.close()
            raise

    async def close(self) -> None:
        """Закрывает пул соединений"""
        if self._pool and not self._pool.closed:
            self._pool.close()
            await self._pool.wait_closed()

    async def check_connection(self) -> bool:
        """Проверяет подключение к Redis"""
        try:
            async with self.connection() as conn:
                return await conn.ping()
        except Exception as e:
            raise RedisError(f"Redis connection failed: {str(e)}") from e


# Инициализация клиента с настройками
redis_client = RedisClient(settings=settings.redis)
