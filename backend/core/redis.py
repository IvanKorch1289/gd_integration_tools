from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, AsyncIterator, Callable, Dict, Optional

import asyncio
import hashlib
import json_tricks
from aioredis import create_redis_pool
from pydantic import BaseModel

from backend.core.logging_config import app_logger
from backend.core.settings import settings
from backend.core.utils import singleton, utilities


class RedisClient:
    """
    Класс для управления пулом соединений с Redis.

    Атрибуты:
        _pool (Optional[asyncio.Future]): Пул соединений с Redis.
        _lock (asyncio.Lock): Блокировка для синхронизации доступа к пулу.
        _ref_count (int): Счетчик ссылок на пул.
    """

    def __init__(self):
        self._pool: Optional[asyncio.Future] = None
        self._lock = asyncio.Lock()  # Для синхронизации доступа к пулу
        self._ref_count = 0  # Счетчик ссылок на пул

    async def _create_pool(self) -> None:
        """
        Создает пул соединений Redis, если он еще не создан.
        """
        async with self._lock:  # Синхронизация доступа
            if self._pool is None or self._pool.done():
                self._pool = asyncio.ensure_future(
                    create_redis_pool(
                        (
                            settings.redis_settings.redis_host,
                            settings.redis_settings.redis_port,
                        ),
                        db=settings.redis_settings.redis_db_cashe,
                        encoding=settings.redis_settings.redis_encoding,
                    )
                )
                await self._pool

    async def _get_connection(self) -> asyncio.Future:
        """
        Возвращает соединение с Redis. Если пул не создан, создает его.

        Returns:
            asyncio.Future: Соединение с Redis.
        """
        await self._create_pool()
        self._ref_count += 1  # Увеличиваем счетчик ссылок
        return await self._pool  # Ожидаем завершения Future

    async def _close(self) -> None:
        """
        Закрывает пул соединений, если он больше не используется.
        """
        self._ref_count -= 1  # Уменьшаем счетчик ссылок
        if self._ref_count == 0 and self._pool is not None and not self._pool.done():
            pool = await self._pool
            pool.close()
            await pool.wait_closed()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[asyncio.Future]:
        """
        Контекстный менеджер для работы с соединением Redis.

        Yields:
            asyncio.Future: Соединение с Redis.
        """
        conn = await self._get_connection()
        try:
            yield conn
        finally:
            await self._close()


# Глобальный экземпляр RedisClient
redis_client = RedisClient()


@singleton
class CachingDecorator:
    """
    Декоратор для кэширования результатов функций в Redis.

    Атрибуты:
        expire (int): Время жизни кэша в секундах.
    """

    def __init__(
        self, expire: int = settings.redis_settings.redis_cache_expire_seconds
    ):
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
