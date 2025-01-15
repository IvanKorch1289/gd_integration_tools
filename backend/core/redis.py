import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from functools import wraps
from typing import Any, AsyncIterator, Callable, Dict, Optional, Union

import asyncio
import json_tricks
from aioredis import create_redis_pool
from pydantic import BaseModel

from backend.core.logging_config import app_logger
from backend.core.settings import settings
from backend.core.utils import singleton


# Пользовательский кодировщик и декодировщик
def custom_encoder(obj):
    if isinstance(obj, uuid.UUID):
        return {"__uuid__": True, "value": str(obj)}
    elif isinstance(obj, datetime):
        return {"__datetime__": True, "value": obj.isoformat()}
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def custom_decoder(dct):
    if "__uuid__" in dct:
        return uuid.UUID(dct["value"])
    elif "__datetime__" in dct:
        return datetime.fromisoformat(dct["value"])
    return dct


class RedisClient:
    def __init__(self):
        self._pool: Optional[asyncio.Future] = None

    async def _create_pool(self) -> None:
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
        await self._create_pool()
        return self._pool.result()

    async def _close(self) -> None:
        if self._pool is not None and not self._pool.done():
            pool = self._pool.result()
            pool.close()
            await pool.wait_closed()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[asyncio.Future]:
        conn = await self._get_connection()
        try:
            yield conn
        finally:
            await self._close()


redis_client = RedisClient()


@singleton
class CachingDecorator:
    def __init__(
        self, expire: int = settings.redis_settings.redis_cache_expire_seconds
    ):
        self.expire = expire

    async def get_cached_data(self, key: str) -> Dict[str, Union[Any, int, None]]:
        try:
            async with redis_client.connection() as r:
                cached_data = await r.get(key)
                if cached_data is None:
                    return {"data": None, "ttl": None, "error": None}

                if isinstance(cached_data, bytes):
                    cached_data = cached_data.decode("utf-8")

                ttl = await r.ttl(key)
                return {
                    "data": json_tricks.loads(
                        cached_data, extra_obj_pairs_hooks=[custom_decoder]
                    ),
                    "ttl": ttl,
                    "error": None,
                }
        except Exception as exc:
            error_message = f"Error getting cached data: {exc}"
            app_logger.error(error_message)
            return {"data": None, "ttl": None, "error": error_message}

    async def cache_data(self, key: str, data: Any) -> None:
        if data is None:
            return

        async def _cache_data():
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
                        data_dict, extra_obj_encoders=[custom_encoder]
                    )
                    await r.set(key, encoded_data, expire=self.expire)
            except Exception as exc:
                app_logger.error(f"Error caching data: {exc}")

        asyncio.create_task(_cache_data())

    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            cache = kwargs.pop("cache", True)
            if not cache:
                result = await func(*args, **kwargs)
                return {"data": result, "from_cache": False, "ttl": None, "error": None}

            key = (
                f"{args[0].__class__.__name__ if args else ''}.{func.__name__}.{kwargs}"
            )
            cached_data = await self.get_cached_data(key)
            if cached_data["data"] is not None:
                return {
                    "data": cached_data["data"],
                    "from_cache": True,
                    "ttl": cached_data["ttl"],
                    "error": cached_data["error"],
                }

            result = await func(*args, **kwargs)
            await self.cache_data(key, result)
            return {
                "data": result,
                "from_cache": False,
                "ttl": self.expire,
                "error": None,
            }

        return wrapper


caching_decorator = CachingDecorator()
