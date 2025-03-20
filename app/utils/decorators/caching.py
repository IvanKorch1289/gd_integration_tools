from functools import wraps
from typing import Any, Callable, Coroutine, Dict, Tuple


__all__ = (
    "response_cache",
    "metadata_cache",
    "existence_cache",
)


class CachingDecorator:
    """Декоратор для кэширования результатов функций в Redis.

    Обеспечивает:
    - Кэширование результатов функций
    - Инвалидацию кэша по ключу или шаблону
    - Поддержку синхронных и асинхронных функций
    - Гибкую настройку времени жизни кэша
    """

    def __init__(
        self,
        expire: int = None,
        key_prefix: str = None,
        exclude_self: bool = True,
        renew_ttl: bool = False,
        key_builder: Callable | None = None,
    ):
        """
        Инициализирует декоратор.

        Аргументы:
            expire (int): Время жизни кэша в секундах
            key_prefix (str): Префикс для ключей кэша
            exclude_self (bool): Исключать self из ключа для методов класса
            renew_ttl (bool): Обновлять время жизни при каждом обращении
            key_builder (Callable): Функция для построения ключа кэша
        """
        from app.config.settings import settings
        from app.utils.logging_service import redis_logger

        self.expire = expire or settings.redis.cache_expire_seconds
        self.key_prefix = key_prefix
        self.exclude_self = exclude_self
        self.renew_ttl = renew_ttl
        self.logger = redis_logger
        self.key_builder = key_builder or self._default_key_builder

    def _default_key_builder(
        self, func: Callable, args: Tuple[Any], kwargs: Dict[str, Any]
    ) -> str:
        """Создает ключ кэша на основе функции и её аргументов."""
        import hashlib

        from json_tricks import dumps

        from app.utils.utils import utilities

        key_data = {
            "module": func.__module__,
            "name": func.__name__,
            "args": args[1:] if self.exclude_self and args else args,
            "kwargs": kwargs,
        }
        serialized = dumps(
            key_data,
            extra_obj_encoders=[utilities.custom_json_encoder],
            separators=(",", ":"),
        )
        return f"{self.key_prefix}:{hashlib.sha256(serialized.encode()).hexdigest()}"

    async def invalidate(self, *cache_keys: str) -> None:
        """Инвалидирует кэш по указанным ключам."""
        from app.infra.clients.redis import redis_client

        try:
            async with redis_client.connection() as r:
                await r.unlink(*cache_keys)
        except Exception as exc:
            self.logger.error(
                f"Ошибка инвалидации кэша: {str(exc)}", exc_info=True
            )

    async def invalidate_pattern(self, pattern: str = None) -> None:
        """Инвалидирует кэш по шаблону ключей."""
        from app.infra.clients.redis import redis_client

        try:
            async with redis_client.connection() as r:
                match_pattern = (
                    f"{self.key_prefix}{pattern}:*"
                    if pattern
                    else f"{self.key_prefix}*"
                )
                _, keys = await r.scan(
                    match=match_pattern,
                    count=10000,
                )
                if keys:
                    await r.unlink(*keys)
                    self.logger.info(
                        f"Ключи по шаблону '{pattern}' инвалидированы"
                    )
        except Exception as exc:
            self.logger.error(
                f"Ошибка инвалидации по шаблону: {str(exc)}", exc_info=True
            )

    def __call__(self, func: Callable) -> Callable:
        """Декорирует функцию, добавляя кэширование."""
        import asyncio

        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            cache_key = self.key_builder(func, args, kwargs)
            cached_value = await self._get_cached_value(cache_key)

            if cached_value is not None:
                return cached_value

            result = await func(*args, **kwargs)
            await self._cache_result(cache_key, result)
            return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Coroutine:
            return async_wrapper(*args, **kwargs)

        return (
            async_wrapper
            if asyncio.iscoroutinefunction(func)
            else sync_wrapper
        )

    async def _get_cached_value(self, key: str) -> Any:
        """Получает значение из кэша."""
        from json_tricks import loads

        from app.infra.clients.redis import redis_client
        from app.utils.utils import utilities

        try:
            async with redis_client.connection() as r:
                data = await r.get(key)
                if data is None:
                    return None

                decoded = await utilities.decode_bytes(data)
                deserialized = loads(
                    decoded,
                    extra_obj_pairs_hooks=[utilities.custom_json_decoder],
                )

                if self.renew_ttl:
                    await r.expire(key, self.expire)

                return deserialized
        except Exception as exc:
            self.logger.error(f"Ошибка чтения кэша: {str(exc)}", exc_info=True)
            return None

    async def _cache_result(self, key: str, result: Any) -> None:
        """Сохраняет результат в кэш."""
        from json_tricks import dumps

        from app.infra.clients.redis import redis_client
        from app.utils.utils import utilities

        try:
            if result is None:
                return

            async with redis_client.connection() as r:
                converted_data = utilities.convert_data(result)
                serialized = dumps(
                    converted_data,
                    extra_obj_encoders=[utilities.custom_json_encoder],
                    separators=(",", ":"),
                )
                await r.setex(key, self.expire, serialized)
        except Exception as exc:
            self.logger.error(
                f"Ошибка записи в кэш: {str(exc)}", exc_info=True
            )


# Глобальные экземпляры декоратора
response_cache = CachingDecorator(
    key_prefix="cache:",
    expire=1800,
    key_builder=lambda func, args, kwargs: (
        f"cache:"
        f"{args[0].__class__.__name__ if hasattr(args[0], "__class__") else args[0].__name__}"
        f":{func.__name__ if hasattr(args[0], "__class__") else None}"
        f"{":".join(str(arg) for arg in args[1:])}:"
        f"{":".join(f'{k}={v}' for k, v in kwargs.items())}"
    ),
)

metadata_cache = CachingDecorator(
    key_prefix="s3:metadata",
    expire=300,
    renew_ttl=True,
    key_builder=lambda func, args, kwargs: f"s3:metadata:{kwargs.get("key", "")}",
)

existence_cache = CachingDecorator(
    key_prefix="s3:exists",
    expire=60,
    key_builder=lambda func, args, kwargs: f"s3:exists:{kwargs.get("key", "")}",
)
