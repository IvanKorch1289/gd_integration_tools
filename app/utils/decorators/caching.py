from functools import wraps
from typing import Any, Callable, Coroutine, Optional

from json_tricks import dumps, loads

from app.config.settings import settings
from app.infra.clients.redis import redis_client
from app.utils.logging_service import redis_logger
from app.utils.utils import utilities


__all__ = (
    "response_cache",
    "metadata_cache",
    "existence_cache",
)


class CachingDecorator:
    def __init__(
        self,
        expire: int = settings.redis.cache_expire_seconds,
        key_prefix: str = None,
        exclude_self: bool = True,
        renew_ttl: bool = False,
        key_builder: Optional[Callable] = None,
    ):
        self.expire = expire
        self.key_prefix = key_prefix
        self.exclude_self = exclude_self
        self.renew_ttl = renew_ttl
        self.logger = redis_logger
        self.key_builder = key_builder or self._default_key_builder

    def _default_key_builder(
        self, func: Callable, args: tuple, kwargs: dict
    ) -> str:
        """Default cache key builder with hash-based normalization"""
        import hashlib

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
        self.logger.critical(serialized)
        return f"{self.key_prefix}:{hashlib.sha256(serialized.encode()).hexdigest()}"

    @redis_client.reconnect_on_failure
    async def invalidate(self, *cache_keys: str) -> None:
        """Invalidate cache for specific keys"""
        try:
            async with redis_client.connection() as r:
                await r.unlink(*cache_keys)
        except Exception as exc:
            self.logger.error(
                f"Cache invalidation failed: {str(exc)}", exc_info=True
            )

    @redis_client.reconnect_on_failure
    async def invalidate_pattern(self, pattern: str = None) -> None:
        """Invalidate cache keys matching pattern"""
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
                        f"Keys for pattern '{pattern}' invalidated"
                    )
        except Exception:
            self.logger.error(
                "Pattern cache invalidation failed", exc_info=True
            )

    def __call__(self, func: Callable) -> Callable:
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

    @redis_client.reconnect_on_failure
    async def _get_cached_value(self, key: str) -> Any:
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
        except Exception:
            self.logger.error("Cache read error", exc_info=True)
            return None

    @redis_client.reconnect_on_failure
    async def _cache_result(self, key: str, result: Any) -> None:
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
        except Exception:
            self.logger.error("Cache write error", exc_info=True)


# Глобальный экземпляр декоратора
response_cache = CachingDecorator(
    key_prefix="cache:",
    expire=1800,
    key_builder=lambda func, args, kwargs: (
        f"cache:"
        f"{args[0].__class__.__name__ if hasattr(args[0], "__class__") else args[0].__name__}"  # Имя класса или функции
        f":{func.__name__ if hasattr(args[0], "__class__") else None}"  # Имя метода класса
        f"{":".join(str(arg) for arg in args[1:])}:"  # Остальные позиционные аргументы
        f"{":".join(f'{k}={v}' for k, v in kwargs.items())}"  # Именованные аргументы
    ),
)

# Экземпляры для файлового хранилища
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
