from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncio
from aioredis import create_redis_pool

from backend.core.settings import settings


class RedisClient:
    def __init__(self):
        self._pool: asyncio.Future | None = None

    async def _create_pool(self) -> None:
        """Создание пула соединений с Redis."""
        if self._pool is None or self._pool.done():
            self._pool = asyncio.ensure_future(
                create_redis_pool(
                    (
                        settings.redis_settings.redis_host,
                        settings.redis_settings.redis_port,
                    ),
                    db=settings.redis_settings.redis_db_cashe,
                    # password=settings.redis_settings.redis_pass,
                    encoding=settings.redis_settings.redis_encoding,
                )
            )
            await self._pool

    async def _get_connection(self) -> asyncio.Future:
        """Получение соединения из пула."""
        await self._create_pool()
        return self._pool.result()

    async def _close(self) -> None:
        """Закрытие всех соединений в пуле."""
        if self._pool is not None and not self._pool.done():
            pool = self._pool.result()
            pool.close()
            await pool.wait_closed()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[asyncio.Future]:
        """Контекстный менеджер для работы с подключением к Redis."""
        conn = await self._get_connection()
        try:
            yield conn
        finally:
            await self._close()


redis = RedisClient()
