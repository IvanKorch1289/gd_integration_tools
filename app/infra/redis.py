from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, AsyncIterator, Callable, Dict, Optional

import asyncio
import hashlib
import json_tricks
from aioredis import Redis, RedisError, create_redis_pool
from pydantic import BaseModel

from app.config.settings import RedisSettings, settings
from app.utils.logging import app_logger
from app.utils.utils import singleton, utilities


__all__ = (
    "redis_client",
    "caching_decorator",
)


class RedisClient:
    """
    Класс для управления пулом соединений с Redis.

    Attributes:
        _pool (Optional[Redis]): Пул соединений с Redis
        _lock (asyncio.Lock): Блокировка для синхронизации доступа
        _ref_count (int): Счетчик активных соединений
        settings (RedisSettings): Конфигурация подключения к Redis
    """

    def __init__(self, settings):
        """
        Инициализация клиента с настройками подключения

        Args:
            settings: Объект с параметрами подключения к Redis
        """
        self._pool: Optional[Redis] = None
        self._lock = asyncio.Lock()
        self._ref_count = 0
        self.settings: RedisSettings = settings

    async def _create_pool(self) -> None:
        """Создает пул соединений с Redis"""
        async with self._lock:
            if self._pool is None or self._pool.closed:
                self._pool = await create_redis_pool(
                    address=(self.settings.redis_host, self.settings.redis_port),
                    db=self.settings.redis_db_cache,
                    # password=self.settings.redis_pass,
                    encoding=self.settings.redis_encoding,
                    timeout=self.settings.redis_timeout,
                    minsize=self.settings.redis_pool_minsize,
                    ssl=self.settings.redis_use_ssl,
                )

    async def _get_connection(self) -> Redis:
        """Возвращает соединение из пула"""
        await self._create_pool()
        self._ref_count += 1
        return self._pool

    async def _close(self) -> None:
        """Уменьшает счетчик активных соединений"""
        self._ref_count -= 1
        if self._ref_count == 0 and self._pool and not self._pool.closed:
            self._pool.close()
            await self._pool.wait_closed()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[Redis]:
        """Контекстный менеджер для работы с соединением"""
        conn = await self._get_connection()
        try:
            yield conn
        finally:
            await self._close()

    @classmethod
    async def health_check_redis(cls) -> bool:
        """Проверяет подключение к Redis.

        Returns:
            bool: True, если подключение успешно.

        Raises:
            HTTPException: Если подключение к Redis не удалось.
        """
        from app.infra.redis import redis_client

        try:
            async with redis_client.connection() as r:
                await r.ping()
            return True
        except Exception as exc:
            raise RedisError(
                detail=f"Redis not connected: {str(exc)}",
            )


# Инициализация клиента с настройками
redis_client = RedisClient(settings=settings.redis)


@singleton
class CachingDecorator:
    """
    Декоратор для кэширования результатов функций в Redis.

    Атрибуты:
        expire (int): Время жизни кэша в секундах.
    """

    def __init__(self, expire: int = settings.redis.redis_cache_expire_seconds):
        """
        Инициализирует декоратор с указанным временем жизни кэша.

        Args:
            expire (int): Время жизни кэша в секундах.
        """
        self.expire = expire

    def _generate_cache_key(self, func: Callable, args: Any, kwargs: Any) -> str:
        """
        Генерирует уникальный ключ для кэширования на основе функции и ее аргументов.

        Args:
            func (Callable): Функция, результат которой кэшируется.
            args (Any): Позиционные аргументы функции.
            kwargs (Any): Именованные аргументы функции.

        Returns:
            str: Уникальный ключ для кэширования.
        """
        key_parts = [func.__module__, func.__name__, str(args), str(kwargs)]
        key_string = ".".join(key_parts)
        return hashlib.md5(key_string.encode("utf-8")).hexdigest()

    async def get_cached_data(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Получает данные из кэша по ключу.

        Args:
            key (str): Ключ для поиска в кэше.

        Returns:
            Optional[Dict[str, Any]]: Данные из кэша или None, если данные отсутствуют или произошла ошибка.
        """
        try:
            async with redis_client.connection() as r:
                cached_data = await r.get(key)
                if cached_data is None:
                    return None

                if isinstance(cached_data, bytes):
                    cached_data = cached_data.decode("utf-8")

                return json_tricks.loads(
                    cached_data, extra_obj_pairs_hooks=[utilities.custom_decoder]
                )
        except Exception as exc:
            app_logger.error(f"Error getting cached data: {exc}")
            raise  # Пробрасываем исключение для обработки вызывающим кодом

    async def cache_data(self, key: str, data: Any) -> None:
        """
        Сохраняет данные в кэш.

        Args:
            key (str): Ключ для сохранения данных.
            data (Any): Данные для кэширования.
        """
        if data is None or (isinstance(data, list) and len(data) == 0):
            return

        try:
            async with redis_client.connection() as r:
                if isinstance(data, BaseModel):
                    data_dict = data.model_dump()
                elif isinstance(data, list) and all(
                    isinstance(item, BaseModel) for item in data
                ):
                    data_dict = [item.model_dump() for item in data]
                else:
                    data_dict = data

                encoded_data = json_tricks.dumps(
                    data_dict, extra_obj_encoders=[utilities.custom_encoder]
                )
                await r.set(key, encoded_data, expire=self.expire)
        except Exception as exc:
            app_logger.error(f"Error caching data: {exc}")
            raise  # Пробрасываем исключение для обработки вызывающим кодом

    def __call__(self, func: Callable) -> Callable:
        """
        Декоратор для кэширования результатов функции.

        Args:
            func (Callable): Функция, результат которой нужно кэшировать.

        Returns:
            Callable: Обернутая функция с поддержкой кэширования.
        """

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            """
            Обертка для функции, которая добавляет кэширование.

            Args:
                *args (Any): Позиционные аргументы функции.
                **kwargs (Any): Именованные аргументы функции.

            Returns:
                Dict[str, Any]: Результат выполнения функции.
            """
            key = self._generate_cache_key(func, args, kwargs)  # Генерируем ключ
            cached_data = await self.get_cached_data(key)

            if cached_data is not None:
                return cached_data

            result = await func(*args, **kwargs)
            await self.cache_data(key, result)  # Сохраняем результат в кэш
            return result

        return wrapper


# Глобальный экземпляр декоратора
caching_decorator = CachingDecorator()
