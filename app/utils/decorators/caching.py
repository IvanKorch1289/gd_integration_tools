import hashlib
from functools import wraps
from typing import Any, Callable, Optional

import json_tricks
from redis.asyncio.client import Redis

from app.config.settings import settings
from app.infra.redis import redis_client
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
        key_prefix: str = "",
        exclude_self: bool = True,
        renew_ttl: bool = False,
    ):
        self.expire = expire
        self.key_prefix = key_prefix
        self.exclude_self = exclude_self
        self.renew_ttl = renew_ttl
        self.logger = redis_logger

    def _generate_cache_key(
        self,
        func: Callable,
        args: tuple,
        kwargs: dict,
        bucket: Optional[str] = None,
    ) -> str:
        """Генерация уникального ключа кэша"""
        prefix = "cache:"

        key_data = {
            "func": f"{func.__module__}.{func.__name__}",
            "args": (
                args[1:] if args and hasattr(args[0], "__dict__") else args
            ),
            "kwargs": kwargs,
            "bucket": bucket,
        }
        if hasattr(args[0], "__class__"):
            prefix += str(args[0].__class__.__name__)
        else:
            prefix += str(args[0].__name__)

        if bucket:
            prefix += f":{bucket}"
        return f"{prefix}:{hashlib.sha256(json_tricks.dumps(key_data, extra_obj_encoders=[utilities.custom_json_encoder]).encode()).hexdigest()}"

    async def _handle_ttl(self, key: str, redis: Redis):
        if self.renew_ttl:
            await redis.expire(key, self.expire)

    @redis_client.reconnect_on_failure
    async def get_cached_data(self, key: str) -> Optional[Any]:
        try:
            async with redis_client.connection() as r:
                data = await r.get(key)
                if data is None:
                    return None

                if isinstance(data, bytes):
                    data = data.decode("utf-8")

                result = json_tricks.loads(
                    data, extra_obj_pairs_hooks=[utilities.custom_json_decoder]
                )
                await self._handle_ttl(key, r)
                return result
        except Exception:
            self.logger.error("Failed to get cached data", exc_info=True)
            return None

    @redis_client.reconnect_on_failure
    async def cache_data(self, key: str, data: Any) -> None:
        try:
            async with redis_client.connection() as r:
                # Преобразуем данные и сериализуем
                converted_data = utilities.convert_data(data)
                serialized = json_tricks.dumps(
                    converted_data,
                    extra_obj_encoders=[utilities.custom_json_encoder],
                )

                await r.setex(key, self.expire, serialized)
        except Exception:
            self.logger.error("Failed to cache data", exc_info=True)

    @redis_client.reconnect_on_failure
    async def clear_cache_with_prefix(self, prefix):
        # Получаем список ключей, начинающихся с заданного префикса
        async with redis_client.connection() as r:
            _, keys = await r.scan(match=f"*{prefix}*")

            if keys:
                await r.delete(*keys)

    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            instance = args[0] if len(args) > 0 else None
            bucket = getattr(instance, "bucket", None) if instance else None

            key = self._generate_cache_key(func, args, kwargs, bucket)
            cached = await self.get_cached_data(key)

            if cached is not None:
                return cached

            result = await func(*args, **kwargs)
            await self.cache_data(key, result)
            return result

        return wrapper


# Глобальный экземпляр декоратора
response_cache = CachingDecorator()

# Экземпляры для файлового хранилища
metadata_cache = CachingDecorator(
    key_prefix="minio:metadata", expire=300, renew_ttl=True  # 5 минут
)

existence_cache = CachingDecorator(
    key_prefix="minio:exists", expire=60, renew_ttl=False  # 1 минута
)
