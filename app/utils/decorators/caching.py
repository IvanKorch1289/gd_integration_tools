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

    def _generate_cache_key(
        self,
        func: Callable,
        args: tuple,
        kwargs: dict,
        bucket: Optional[str] = None,
    ) -> str:
        key_parts = [
            self.key_prefix,
            f"{args[0].__class__.__name__ if args else ''}.{func.__name__}.{kwargs}",
        ]

        if bucket:
            key_parts.insert(0, f"bucket:{bucket}")

        key_string = ":".join(key_parts)

        return hashlib.sha256(key_string.encode()).hexdigest()

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
        except Exception as exc:
            redis_logger.error(f"Failed to get cached data: {str(exc)}")
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
        except Exception as exc:
            redis_logger.error(f"Failed to cache data: {str(exc)}")

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
