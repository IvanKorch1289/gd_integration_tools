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
    """Управляет пулом подключений к Redis с поддержкой асинхронных операций.

    Обеспечивает безопасное создание и закрытие подключений, проверку работоспособности
    и автоматическое восстановление соединений.

    Attributes:
        _pool (Optional[Redis]): Основной пул подключений
        _lock (asyncio.Lock): Блокировка для синхронизации инициализации пула
        settings (RedisSettings): Конфигурационные параметры подключения
    """

    def __init__(self, settings: RedisSettings):
        """Инициализирует клиент с указанными настройками подключения.

        Args:
            settings (RedisSettings): Конфигурация подключения к Redis, содержит:
                - redis_host: Хост Redis
                - redis_port: Порт Redis
                - redis_db_cache: Номер базы данных
                - redis_pass: Пароль (опционально)
                - redis_encoding: Кодировка данных
                - redis_timeout: Таймаут подключения
                - redis_pool_minsize: Минимальный размер пула
                - redis_use_ssl: Использовать SSL подключение
        """
        self._pool: Optional[Redis] = None
        self._lock = asyncio.Lock()
        self.settings = settings

    async def _ensure_pool(self) -> None:
        """Создает или обновляет пул подключений при необходимости.

        Гарантирует безопасную инициализацию пула с использованием блокировки.

        Raises:
            RedisError: Если не удалось установить подключение
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
        """Предоставляет асинхронный контекст для работы с подключением.

        Пример использования:
            async with redis_client.connection() as conn:
                await conn.set("key", "value")

        Yields:
            Redis: Активное подключение к Redis

        Raises:
            RedisError: При возникновении проблем с подключением
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
        """Корректно закрывает все подключения и освобождает ресурсы.

        Должен вызываться при завершении работы приложения.
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
        """Проверяет работоспособность подключения к Redis.

        Returns:
            bool: True если подключение активно, False в случае ошибок

        Пример использования:
            if await redis_client.check_connection():
                print("Connected to Redis")
        """
        try:
            async with self.connection() as conn:
                return await conn.ping()
        except RedisError:
            return False

    async def dispose(self) -> None:
        """Алиас для метода close(). Предназначен для явного завершения работы."""
        await self.close()


# Инициализация клиента с настройками
redis_client = RedisClient(settings=settings.redis)
