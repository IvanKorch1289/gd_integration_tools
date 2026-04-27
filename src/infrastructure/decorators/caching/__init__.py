"""Multi-layer кэширование с Redis → Memory → Disk fallback chain.

Публичные экземпляры:
    response_cache — общий response cache (expire=1800, disk+memory).
    metadata_cache — кэш метаданных S3 (expire=300, memory only).
    existence_cache — кэш проверки существования S3 (expire=60).
"""

import hashlib
from typing import Any, Awaitable, Callable

from src.infrastructure.decorators.caching.decorator import CachingDecorator
from src.utilities.json_codec import json_dumps

__all__ = (
    "response_cache",
    "metadata_cache",
    "existence_cache",
    "CachingDecorator",
    "close_caches",
)


def _stable_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json_dumps(payload)).hexdigest()


def response_cache_key(
    func: Callable[..., Awaitable[Any]], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> str:
    owner = (
        args[0].__class__.__name__
        if args and hasattr(args[0], "__class__")
        else func.__module__
    )
    payload = {"args": args[1:] if args else (), "kwargs": dict(sorted(kwargs.items()))}
    return f"cache:{owner}:{func.__name__}:{_stable_hash(payload)}"


def metadata_cache_key(
    func: Callable[..., Awaitable[Any]], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> str:
    key = kwargs.get("key")
    if key is None and len(args) > 1:
        key = args[1]
    return f"s3:metadata:{key or ''}"


def existence_cache_key(
    func: Callable[..., Awaitable[Any]], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> str:
    key = kwargs.get("key")
    if key is None and len(args) > 1:
        key = args[1]
    return f"s3:exists:{key or ''}"


response_cache = CachingDecorator(
    key_prefix="cache",
    expire=1800,
    key_builder=response_cache_key,
    use_memory_fallback=True,
    memory_max_size=2048,
    use_disk_fallback=True,
    disk_directory=".cache/external-requests",
    disk_write_through=True,
    stale_if_error_seconds=300,
    allow_stale_on_error=True,
    redis_failures_threshold=3,
    redis_cooldown_seconds=10,
)

metadata_cache = CachingDecorator(
    key_prefix="s3:metadata",
    expire=300,
    renew_ttl=True,
    key_builder=metadata_cache_key,
    use_memory_fallback=True,
    memory_max_size=1024,
    use_disk_fallback=False,
    stale_if_error_seconds=60,
    allow_stale_on_error=True,
    redis_failures_threshold=3,
    redis_cooldown_seconds=10,
)

existence_cache = CachingDecorator(
    key_prefix="s3:exists",
    expire=60,
    key_builder=existence_cache_key,
    use_memory_fallback=True,
    memory_max_size=1024,
    use_disk_fallback=False,
    stale_if_error_seconds=15,
    allow_stale_on_error=True,
    redis_failures_threshold=3,
    redis_cooldown_seconds=10,
)


async def close_caches() -> None:
    await response_cache.close()
    await metadata_cache.close()
    await existence_cache.close()
