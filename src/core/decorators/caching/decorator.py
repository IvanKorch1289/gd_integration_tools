import asyncio
import hashlib
import time
from functools import wraps
from pathlib import Path
from typing import Any, Awaitable, Callable

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core.config.settings import settings
from app.core.decorators.caching.stampede import KeyLockManager
from app.core.decorators.caching.storage.disk import DiskTTLCache
from app.core.decorators.caching.storage.memory import InMemoryTTLCache
from app.infrastructure.clients.storage.redis import redis_client
from app.infrastructure.external_apis.logging_service import redis_logger
from app.utilities.json_codec import json_dumps, json_loads

__all__ = ("CachingDecorator",)


class CachingDecorator:
    """Декоратор кэширования async-функций с multi-layer fallback.

    Слои (в порядке приоритета):
        1. Redis — основной shared-кэш между процессами.
        2. Memory — быстрый локальный in-process fallback.
        3. Disk — устойчивый fallback между рестартами.
    """

    def __init__(
        self,
        expire: int | None = None,
        key_prefix: str | None = None,
        exclude_self: bool = True,
        renew_ttl: bool = False,
        key_builder: Callable[..., str] | None = None,
        use_memory_fallback: bool = True,
        memory_max_size: int = 1024,
        use_disk_fallback: bool = False,
        disk_directory: str | Path | None = None,
        disk_write_through: bool = False,
        repopulate_redis_from_fallback: bool = True,
        stale_if_error_seconds: int = 0,
        allow_stale_on_error: bool = True,
        redis_failures_threshold: int = 3,
        redis_cooldown_seconds: int = 10,
    ) -> None:
        self.expire = expire or settings.redis.cache_expire_seconds
        self.key_prefix = key_prefix or "cache"
        self.exclude_self = exclude_self
        self.renew_ttl = renew_ttl
        self.key_builder = key_builder or self._default_key_builder
        self.logger = redis_logger

        self.memory_cache = (
            InMemoryTTLCache(memory_max_size) if use_memory_fallback else None
        )

        self.disk_cache = (
            DiskTTLCache(directory=disk_directory or ".cache/external-requests")
            if use_disk_fallback
            else None
        )

        self.disk_write_through = disk_write_through
        self.repopulate_redis_from_fallback = repopulate_redis_from_fallback

        self.stale_if_error_seconds = max(0, stale_if_error_seconds)
        self.allow_stale_on_error = allow_stale_on_error

        self.redis_failures_threshold = max(1, redis_failures_threshold)
        self.redis_cooldown_seconds = max(1, redis_cooldown_seconds)
        self._redis_failures = 0
        self._redis_disabled_until = 0.0

        self._lock_manager = KeyLockManager()

    @staticmethod
    def _now() -> float:
        return time.monotonic()

    def _redis_is_available(self) -> bool:
        return self._now() >= self._redis_disabled_until

    def _mark_redis_success(self) -> None:
        self._redis_failures = 0
        self._redis_disabled_until = 0.0

    def _mark_redis_failure(self) -> None:
        self._redis_failures += 1
        if self._redis_failures >= self.redis_failures_threshold:
            self._redis_disabled_until = self._now() + self.redis_cooldown_seconds

    def _default_key_builder(
        self,
        func: Callable[..., Awaitable[Any]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> str:
        key_data = {
            "module": func.__module__,
            "name": func.__name__,
            "args": args[1:] if self.exclude_self and args else args,
            "kwargs": dict(sorted(kwargs.items())),
        }
        digest = hashlib.sha256(json_dumps(key_data)).hexdigest()
        return f"{self.key_prefix}:{digest}"

    def _pattern(self, pattern: str | None = None) -> str:
        if not pattern:
            return f"{self.key_prefix}*"
        if pattern.startswith(self.key_prefix):
            return pattern
        if self.key_prefix.endswith(":"):
            return f"{self.key_prefix}{pattern}"
        return f"{self.key_prefix}:{pattern}"

    async def invalidate(self, *cache_keys: str) -> None:
        if not cache_keys:
            return

        try:
            await redis_client.cache_delete(*cache_keys)
        except Exception as exc:
            self.logger.error(
                "Ошибка инвалидации Redis cache: %s", str(exc), exc_info=True
            )

        if self.memory_cache:
            await self.memory_cache.delete(*cache_keys)
        if self.disk_cache:
            await self.disk_cache.delete(*cache_keys)

    async def invalidate_pattern(self, pattern: str | None = None) -> None:
        match_pattern = self._pattern(pattern)

        try:
            await redis_client.cache_delete_pattern(match_pattern)
        except Exception as exc:
            self.logger.error(
                "Ошибка pattern invalidation Redis cache: %s", str(exc), exc_info=True
            )

        if self.memory_cache:
            await self.memory_cache.delete_pattern(match_pattern)
        if self.disk_cache:
            await self.disk_cache.delete_pattern(match_pattern)

    def __call__(
        self, func: Callable[..., Awaitable[Any]]
    ) -> Callable[..., Awaitable[Any]]:
        if not asyncio.iscoroutinefunction(func):
            raise TypeError("CachingDecorator поддерживает только async")

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = self.key_builder(func, args, kwargs)

            cached = await self._get_cached_value(key)
            if cached is not None:
                return cached

            lock = await self._lock_manager.get(key)

            try:
                await asyncio.wait_for(
                    lock.acquire(),
                    timeout=self._lock_manager.acquire_timeout,
                )
            except asyncio.TimeoutError:
                self.logger.warning(
                    "Таймаут захвата lock для key=%s, выполняю функцию напрямую",
                    key,
                )
                return await func(*args, **kwargs)

            try:
                cached = await self._get_cached_value(key)
                if cached is not None:
                    return cached

                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    stale = None
                    if self.allow_stale_on_error:
                        stale = await self._get_stale_value(key)
                    if stale is not None:
                        self.logger.warning(
                            "Возвращено stale значение для key=%s после ошибки: %s",
                            key,
                            str(exc),
                        )
                        return stale
                    raise

                await self._cache_result(key, result)
                return result
            finally:
                lock.release()
                await self._lock_manager.cleanup(key, lock)

        return wrapper

    async def close(self) -> None:
        if self.disk_cache:
            await self.disk_cache.close()

    async def _try_repopulate_redis(self, key: str, value: Any) -> None:
        if not self.repopulate_redis_from_fallback:
            return
        if not self._redis_is_available():
            return

        try:
            await redis_client.cache_set(key, json_dumps(value), self.expire)
            self._mark_redis_success()
        except (RedisConnectionError, RedisTimeoutError, RedisError, OSError):
            self._mark_redis_failure()
        except Exception as exc:
            redis_client.logger.warning(
                "Неизвестная ошибка при фоновом обновлении Redis кэша: %s", exc
            )

    async def _get_cached_value(self, key: str) -> Any | None:
        # 1. Redis
        if self._redis_is_available():
            try:
                data = await redis_client.cache_get(key)
                if data is not None:
                    value = json_loads(data)
                    if self.renew_ttl:
                        await redis_client.cache_set(key, data, self.expire)
                    self._mark_redis_success()

                    if self.memory_cache:
                        await self.memory_cache.set(
                            key=key, value=value,
                            ttl_seconds=self.expire,
                            stale_if_error_seconds=self.stale_if_error_seconds,
                        )
                    if self.disk_cache and self.disk_write_through:
                        await self.disk_cache.set(
                            key=key, value=value,
                            ttl_seconds=self.expire,
                            stale_if_error_seconds=self.stale_if_error_seconds,
                        )
                    return value

            except (RedisConnectionError, RedisTimeoutError, RedisError, OSError) as exc:
                self._mark_redis_failure()
                self.logger.warning(
                    "Redis cache недоступен, fallback chain activated: %s", str(exc)
                )
            except Exception as exc:
                self.logger.error(
                    "Ошибка чтения Redis cache: %s", str(exc), exc_info=True
                )

        # 2. Memory
        if self.memory_cache:
            memory_entry = await self.memory_cache.get(key, renew_ttl=self.renew_ttl)
            if memory_entry is not None and memory_entry.is_fresh():
                return memory_entry.value

        # 3. Disk
        if self.disk_cache:
            try:
                disk_entry = await self.disk_cache.get(key, renew_ttl=self.renew_ttl)
                if disk_entry is not None and disk_entry.is_fresh():
                    if self.memory_cache:
                        await self.memory_cache.set(
                            key=key, value=disk_entry.value,
                            ttl_seconds=disk_entry.ttl_seconds or self.expire,
                            stale_if_error_seconds=disk_entry.stale_if_error_seconds,
                        )
                    await self._try_repopulate_redis(key, disk_entry.value)
                    return disk_entry.value
            except Exception as exc:
                self.logger.error(
                    "Ошибка чтения disk cache: %s", str(exc), exc_info=True
                )

        return None

    async def _get_stale_value(self, key: str) -> Any | None:
        if self.memory_cache:
            memory_entry = await self.memory_cache.get(key, renew_ttl=False)
            if memory_entry is not None and memory_entry.is_alive():
                return memory_entry.value

        if self.disk_cache:
            try:
                disk_entry = await self.disk_cache.get(key, renew_ttl=False)
                if disk_entry is not None and disk_entry.is_alive():
                    if self.memory_cache:
                        await self.memory_cache.set(
                            key=key, value=disk_entry.value,
                            ttl_seconds=disk_entry.ttl_seconds or self.expire,
                            stale_if_error_seconds=disk_entry.stale_if_error_seconds,
                        )
                    return disk_entry.value
            except Exception as exc:
                self.logger.error(
                    "Ошибка чтения stale из disk cache: %s", str(exc), exc_info=True
                )

        return None

    async def _cache_result(self, key: str, result: Any) -> None:
        if result is None:
            return

        if self.memory_cache:
            await self.memory_cache.set(
                key=key, value=result,
                ttl_seconds=self.expire,
                stale_if_error_seconds=self.stale_if_error_seconds,
            )

        if self.disk_cache and self.disk_write_through:
            try:
                await self.disk_cache.set(
                    key=key, value=result,
                    ttl_seconds=self.expire,
                    stale_if_error_seconds=self.stale_if_error_seconds,
                )
            except Exception as exc:
                self.logger.error(
                    "Ошибка записи disk cache: %s", str(exc), exc_info=True
                )

        if not self._redis_is_available():
            return

        try:
            await redis_client.cache_set(key, json_dumps(result), self.expire)
            self._mark_redis_success()
        except (RedisConnectionError, RedisTimeoutError, RedisError, OSError) as exc:
            self._mark_redis_failure()
            self.logger.warning("Redis cache недоступен при записи: %s", str(exc))
        except Exception as exc:
            self.logger.error("Ошибка записи Redis cache: %s", str(exc), exc_info=True)
