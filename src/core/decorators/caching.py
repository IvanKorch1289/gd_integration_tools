import asyncio
import fnmatch
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Awaitable, Callable

from diskcache import Cache
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core.config.settings import settings
from app.infrastructure.clients.redis import redis_client
from app.infrastructure.external_apis.logging_service import redis_logger
from app.utilities.json_codec import json_dumps, json_loads

__all__ = (
    "response_cache",
    "metadata_cache",
    "existence_cache",
    "CachingDecorator",
    "close_caches",
)


@dataclass(slots=True)
class CacheEnvelope:
    """
    Унифицированная оболочка записи кэша.

    value:
        Полезное значение.

    ttl_seconds:
        Основной TTL записи. Пока он не истёк, запись считается fresh.

    stale_if_error_seconds:
        Дополнительное время жизни stale-значения.
        Используется только как fail-safe при ошибках источника данных.

    fresh_until:
        Время (monotonic), до которого запись считается fresh.

    stale_until:
        Время (monotonic), до которого запись можно вернуть как stale.
    """

    value: Any
    ttl_seconds: int | None
    stale_if_error_seconds: int
    fresh_until: float | None
    stale_until: float | None

    @staticmethod
    def _calc_deadline(seconds: int | None, now: float) -> float | None:
        if seconds is None or seconds <= 0:
            return None
        return now + seconds

    @classmethod
    def create(
        cls, value: Any, ttl_seconds: int | None, stale_if_error_seconds: int = 0
    ) -> "CacheEnvelope":
        """
        Создаёт новую оболочку кэша на основе TTL и stale-window.
        """
        now = time.monotonic()
        fresh_until = cls._calc_deadline(ttl_seconds, now)

        if fresh_until is None:
            stale_until = None
        else:
            stale_until = fresh_until + max(0, stale_if_error_seconds)

        return cls(
            value=value,
            ttl_seconds=ttl_seconds,
            stale_if_error_seconds=max(0, stale_if_error_seconds),
            fresh_until=fresh_until,
            stale_until=stale_until,
        )

    def renew(self) -> "CacheEnvelope":
        """
        Обновляет TTL записи, сохраняя прежние настройки.
        """
        return self.create(
            value=self.value,
            ttl_seconds=self.ttl_seconds,
            stale_if_error_seconds=self.stale_if_error_seconds,
        )

    def is_fresh(self, now: float | None = None) -> bool:
        """
        Возвращает True, если запись ещё свежая.
        """
        current = time.monotonic() if now is None else now
        return self.fresh_until is None or self.fresh_until > current

    def is_alive(self, now: float | None = None) -> bool:
        """
        Возвращает True, если запись вообще можно использовать
        (fresh или stale).
        """
        current = time.monotonic() if now is None else now
        return self.stale_until is None or self.stale_until > current

    def is_stale(self, now: float | None = None) -> bool:
        """
        Возвращает True, если запись уже не fresh, но ещё жива как stale.
        """
        current = time.monotonic() if now is None else now
        return self.is_alive(current) and not self.is_fresh(current)

    def to_dict(self) -> dict[str, Any]:
        """
        Сериализует envelope в dict.
        """
        return {
            "__cache_envelope__": True,
            "value": self.value,
            "ttl_seconds": self.ttl_seconds,
            "stale_if_error_seconds": self.stale_if_error_seconds,
            "fresh_until": self.fresh_until,
            "stale_until": self.stale_until,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "CacheEnvelope":
        """
        Восстанавливает envelope из payload.

        Поддерживает два формата:
        - новый envelope-формат;
        - старый формат, где в кэше лежало только значение.
        """
        if isinstance(payload, dict) and payload.get("__cache_envelope__") is True:
            return cls(
                value=payload.get("value"),
                ttl_seconds=payload.get("ttl_seconds"),
                stale_if_error_seconds=payload.get("stale_if_error_seconds", 0),
                fresh_until=payload.get("fresh_until"),
                stale_until=payload.get("stale_until"),
            )

        # Обратная совместимость со старым форматом.
        return cls(
            value=payload,
            ttl_seconds=None,
            stale_if_error_seconds=0,
            fresh_until=None,
            stale_until=None,
        )


@dataclass(slots=True)
class MemoryCacheEntry:
    """
    Запись in-memory кэша.
    """

    envelope: CacheEnvelope


class InMemoryTTLCache:
    """
    Простой in-memory LRU + TTL кэш.

    Особенности:
    - хранит envelope с fresh/stale semantics;
    - умеет продлевать TTL при renew_ttl=True;
    - удаляет самые старые записи при переполнении.
    """

    def __init__(self, max_size: int = 1024) -> None:
        self._data: OrderedDict[str, MemoryCacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._max_size = max_size

    @staticmethod
    def _now() -> float:
        return time.monotonic()

    def _purge_dead(self) -> None:
        current = self._now()
        dead_keys = [
            key
            for key, entry in self._data.items()
            if not entry.envelope.is_alive(current)
        ]
        for key in dead_keys:
            self._data.pop(key, None)

    def _evict_if_needed(self) -> None:
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)

    async def get(self, key: str, renew_ttl: bool = False) -> CacheEnvelope | None:
        """
        Возвращает envelope по ключу.
        """
        async with self._lock:
            self._purge_dead()

            entry = self._data.get(key)
            if entry is None:
                return None

            envelope = entry.envelope
            if not envelope.is_alive():
                self._data.pop(key, None)
                return None

            if renew_ttl and envelope.is_fresh() and envelope.ttl_seconds:
                envelope = envelope.renew()
                entry.envelope = envelope

            self._data.move_to_end(key)
            return envelope

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None,
        stale_if_error_seconds: int = 0,
    ) -> None:
        """
        Сохраняет запись в memory cache.
        """
        async with self._lock:
            self._purge_dead()

            self._data[key] = MemoryCacheEntry(
                envelope=CacheEnvelope.create(
                    value=value,
                    ttl_seconds=ttl_seconds,
                    stale_if_error_seconds=stale_if_error_seconds,
                )
            )
            self._data.move_to_end(key)
            self._evict_if_needed()

    async def delete(self, *keys: str) -> None:
        """
        Удаляет записи по ключам.
        """
        async with self._lock:
            for key in keys:
                self._data.pop(key, None)

    async def delete_pattern(self, pattern: str) -> None:
        """
        Удаляет записи по glob-паттерну.
        """
        async with self._lock:
            keys_to_delete = [
                key for key in self._data if fnmatch.fnmatch(key, pattern)
            ]
            for key in keys_to_delete:
                self._data.pop(key, None)


class DiskTTLCache:
    """
    Disk-backed cache на основе diskcache.

    В отличие от старой версии, хранит не только payload,
    но и envelope с fresh/stale метаданными.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._cache = Cache(str(self.directory))

    @staticmethod
    def _storage_expire(
        ttl_seconds: int | None, stale_if_error_seconds: int
    ) -> int | None:
        """
        TTL хранения в diskcache.

        Если включён stale-window, запись живёт дольше основного TTL,
        чтобы её можно было вернуть как fail-safe.
        """
        if ttl_seconds is None or ttl_seconds <= 0:
            return None
        return ttl_seconds + max(0, stale_if_error_seconds)

    @staticmethod
    def _serialize_envelope(envelope: CacheEnvelope) -> bytes:
        """
        Сериализует envelope в bytes.
        """
        return json_dumps(envelope.to_dict())

    @staticmethod
    def _deserialize_envelope(raw: bytes) -> CacheEnvelope | None:
        """
        Десериализует bytes в CacheEnvelope.
        """
        try:
            payload = json_loads(raw)
            return CacheEnvelope.from_payload(payload)
        except Exception:
            return None

    def _get_sync(self, key: str) -> CacheEnvelope | None:
        raw = self._cache.get(key, default=None)
        if raw is None:
            return None

        if isinstance(raw, bytearray):
            raw = bytes(raw)
        elif isinstance(raw, memoryview):
            raw = bytes(raw)

        if not isinstance(raw, bytes):
            return None

        envelope = self._deserialize_envelope(raw)
        if envelope is None:
            return None

        if not envelope.is_alive():
            self._cache.pop(key, default=None)
            return None

        return envelope

    def _set_sync(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None,
        stale_if_error_seconds: int = 0,
    ) -> None:
        envelope = CacheEnvelope.create(
            value=value,
            ttl_seconds=ttl_seconds,
            stale_if_error_seconds=stale_if_error_seconds,
        )

        self._cache.set(
            key,
            self._serialize_envelope(envelope),
            expire=self._storage_expire(ttl_seconds, stale_if_error_seconds),
        )

    def _renew_sync(self, key: str, envelope: CacheEnvelope) -> CacheEnvelope:
        renewed = envelope.renew()
        self._cache.set(
            key,
            self._serialize_envelope(renewed),
            expire=self._storage_expire(
                renewed.ttl_seconds, renewed.stale_if_error_seconds
            ),
        )
        return renewed

    def _delete_sync(self, *keys: str) -> None:
        for key in keys:
            self._cache.pop(key, default=None)

    def _delete_pattern_sync(self, pattern: str) -> None:
        keys_to_delete = [
            key
            for key in self._cache.iterkeys()
            if isinstance(key, str) and fnmatch.fnmatch(key, pattern)
        ]
        for key in keys_to_delete:
            self._cache.pop(key, default=None)

    def _close_sync(self) -> None:
        self._cache.close()

    async def get(self, key: str, renew_ttl: bool = False) -> CacheEnvelope | None:
        """
        Возвращает envelope по ключу.
        """
        envelope = await asyncio.to_thread(self._get_sync, key)

        if (
            envelope is not None
            and renew_ttl
            and envelope.is_fresh()
            and envelope.ttl_seconds
        ):
            envelope = await asyncio.to_thread(self._renew_sync, key, envelope)

        return envelope

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None,
        stale_if_error_seconds: int = 0,
    ) -> None:
        """
        Сохраняет запись в disk cache.
        """
        await asyncio.to_thread(
            self._set_sync, key, value, ttl_seconds, stale_if_error_seconds
        )

    async def delete(self, *keys: str) -> None:
        """
        Удаляет записи по ключам.
        """
        await asyncio.to_thread(self._delete_sync, *keys)

    async def delete_pattern(self, pattern: str) -> None:
        """
        Удаляет записи по glob-паттерну.
        """
        await asyncio.to_thread(self._delete_pattern_sync, pattern)

    async def close(self) -> None:
        """
        Закрывает diskcache.
        """
        await asyncio.to_thread(self._close_sync)


class CachingDecorator:
    """
    Декоратор кэширования async-функций.

    Слои:
    - Redis — основной shared-cache;
    - memory — быстрый локальный fallback;
    - disk — устойчивый локальный fallback между рестартами.

    Основные улучшения относительно прошлой версии:
    - single-flight по cache key, чтобы не было stampede;
    - cooldown для Redis после серии ошибок;
    - stale-on-error для memory/disk fallback;
    - обратная совместимость со старыми disk payload.
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

        self._key_locks: dict[str, asyncio.Lock] = {}
        self._key_locks_guard = asyncio.Lock()

    @staticmethod
    def _now() -> float:
        return time.monotonic()

    def _redis_is_available(self) -> bool:
        """
        Проверяет, не находится ли Redis в cooldown-режиме.
        """
        return self._now() >= self._redis_disabled_until

    def _mark_redis_success(self) -> None:
        """
        Сбрасывает счётчик ошибок Redis.
        """
        self._redis_failures = 0
        self._redis_disabled_until = 0.0

    def _mark_redis_failure(self) -> None:
        """
        Увеличивает счётчик ошибок Redis и при необходимости
        переводит Redis в cooldown-режим.
        """
        self._redis_failures += 1

        if self._redis_failures >= self.redis_failures_threshold:
            self._redis_disabled_until = self._now() + self.redis_cooldown_seconds

    async def _get_key_lock(self, key: str) -> asyncio.Lock:
        """
        Возвращает lock для конкретного cache key.
        """
        async with self._key_locks_guard:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._key_locks[key] = lock
            return lock

    async def _cleanup_key_lock(self, key: str, lock: asyncio.Lock) -> None:
        """
        Аккуратно удаляет lock из реестра, если он больше не нужен.
        """
        async with self._key_locks_guard:
            current = self._key_locks.get(key)
            if current is lock and not lock.locked():
                self._key_locks.pop(key, None)

    def _default_key_builder(
        self,
        func: Callable[..., Awaitable[Any]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> str:
        """
        Строит стабильный cache key по имени функции и её аргументам.
        """
        key_data = {
            "module": func.__module__,
            "name": func.__name__,
            "args": args[1:] if self.exclude_self and args else args,
            "kwargs": dict(sorted(kwargs.items())),
        }
        digest = hashlib.sha256(json_dumps(key_data)).hexdigest()
        return f"{self.key_prefix}:{digest}"

    def _pattern(self, pattern: str | None = None) -> str:
        """
        Нормализует glob-паттерн под текущий key_prefix.
        """
        if not pattern:
            return f"{self.key_prefix}*"

        if pattern.startswith(self.key_prefix):
            return pattern

        if self.key_prefix.endswith(":"):
            return f"{self.key_prefix}{pattern}"

        return f"{self.key_prefix}:{pattern}"

    async def invalidate(self, *cache_keys: str) -> None:
        """
        Инвалидирует точечные cache keys во всех слоях.
        """
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
        """
        Инвалидирует cache keys по паттерну во всех слоях.
        """
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
        """
        Оборачивает async-функцию кэшированием.
        """
        if not asyncio.iscoroutinefunction(func):
            raise TypeError("CachingDecorator поддерживает только async")

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = self.key_builder(func, args, kwargs)

            cached = await self._get_cached_value(key)
            if cached is not None:
                return cached

            lock = await self._get_key_lock(key)

            async with lock:
                try:
                    # Double-check после получения lock.
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
                                "Возвращено stale значение из fallback "
                                "для key=%s после ошибки источника: %s",
                                key,
                                str(exc),
                            )
                            return stale

                        raise

                    await self._cache_result(key, result)
                    return result
                finally:
                    await self._cleanup_key_lock(key, lock)

        return wrapper

    async def close(self) -> None:
        """
        Закрывает используемые локальные кэши.
        """
        if self.disk_cache:
            await self.disk_cache.close()

    async def _try_repopulate_redis(self, key: str, value: Any) -> None:
        """
        Пытается прогреть Redis значением из локального fallback-слоя.
        """
        if not self.repopulate_redis_from_fallback:
            return

        if not self._redis_is_available():
            return

        try:
            await redis_client.cache_set(key, json_dumps(value), self.expire)
            self._mark_redis_success()
        except RedisConnectionError, RedisTimeoutError, RedisError, OSError:
            self._mark_redis_failure()
        except Exception as exc:
            redis_client.logger.warning(
                f"Неизвестная ошибка при фоновом обновлении Redis кэша: {exc}"
            )

    async def _get_cached_value(self, key: str) -> Any | None:
        """
        Читает только fresh-значение.

        Порядок:
        1. Redis
        2. Memory
        3. Disk
        """
        # ------------------------------------------------------------------
        # 1. Redis
        # ------------------------------------------------------------------
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
                            key=key,
                            value=value,
                            ttl_seconds=self.expire,
                            stale_if_error_seconds=self.stale_if_error_seconds,
                        )

                    if self.disk_cache and self.disk_write_through:
                        await self.disk_cache.set(
                            key=key,
                            value=value,
                            ttl_seconds=self.expire,
                            stale_if_error_seconds=self.stale_if_error_seconds,
                        )

                    return value

            except (
                RedisConnectionError,
                RedisTimeoutError,
                RedisError,
                OSError,
            ) as exc:
                self._mark_redis_failure()
                self.logger.warning(
                    "Redis cache недоступен, fallback chain activated: %s", str(exc)
                )
            except Exception as exc:
                self.logger.error(
                    "Ошибка чтения Redis cache: %s", str(exc), exc_info=True
                )

        # ------------------------------------------------------------------
        # 2. Memory
        # ------------------------------------------------------------------
        if self.memory_cache:
            memory_entry = await self.memory_cache.get(key, renew_ttl=self.renew_ttl)
            if memory_entry is not None and memory_entry.is_fresh():
                return memory_entry.value

        # ------------------------------------------------------------------
        # 3. Disk
        # ------------------------------------------------------------------
        if self.disk_cache:
            try:
                disk_entry = await self.disk_cache.get(key, renew_ttl=self.renew_ttl)
                if disk_entry is not None and disk_entry.is_fresh():
                    if self.memory_cache:
                        await self.memory_cache.set(
                            key=key,
                            value=disk_entry.value,
                            ttl_seconds=disk_entry.ttl_seconds or self.expire,
                            stale_if_error_seconds=(disk_entry.stale_if_error_seconds),
                        )

                    await self._try_repopulate_redis(key, disk_entry.value)
                    return disk_entry.value

            except Exception as exc:
                self.logger.error(
                    "Ошибка чтения disk cache: %s", str(exc), exc_info=True
                )

        return None

    async def _get_stale_value(self, key: str) -> Any | None:
        """
        Пытается вернуть stale-значение из локальных fallback-слоёв.

        Используется только как fail-safe при ошибке исходной функции.
        """
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
                            key=key,
                            value=disk_entry.value,
                            ttl_seconds=disk_entry.ttl_seconds or self.expire,
                            stale_if_error_seconds=(disk_entry.stale_if_error_seconds),
                        )
                    return disk_entry.value
            except Exception as exc:
                self.logger.error(
                    "Ошибка чтения stale из disk cache: %s", str(exc), exc_info=True
                )

        return None

    async def _cache_result(self, key: str, result: Any) -> None:
        """
        Кэширует результат во все доступные слои.

        Важный нюанс:
        - None не кэшируем, чтобы не ломать семантику miss;
        - локальные fallback-слои пишем всегда;
        - Redis пишем только если он не в cooldown.
        """
        if result is None:
            return

        if self.memory_cache:
            await self.memory_cache.set(
                key=key,
                value=result,
                ttl_seconds=self.expire,
                stale_if_error_seconds=self.stale_if_error_seconds,
            )

        if self.disk_cache and self.disk_write_through:
            try:
                await self.disk_cache.set(
                    key=key,
                    value=result,
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


def _stable_hash(payload: dict[str, Any]) -> str:
    """
    Возвращает стабильный SHA-256 хэш для произвольного payload.
    """
    return hashlib.sha256(json_dumps(payload)).hexdigest()


def response_cache_key(
    func: Callable[..., Awaitable[Any]], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> str:
    """
    Ключ для общего response cache.
    """
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
    """
    Ключ для кэша метаданных S3.
    """
    key = kwargs.get("key")
    if key is None and len(args) > 1:
        key = args[1]
    return f"s3:metadata:{key or ''}"


def existence_cache_key(
    func: Callable[..., Awaitable[Any]], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> str:
    """
    Ключ для кэша существования объекта S3.
    """
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
    """
    Закрывает локальные fallback-кэши.
    """
    await response_cache.close()
    await metadata_cache.close()
    await existence_cache.close()
