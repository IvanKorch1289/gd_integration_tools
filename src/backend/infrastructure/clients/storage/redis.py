import asyncio
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Awaitable, Callable, Literal

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from src.backend.core.config.settings import RedisSettings, settings
from src.backend.infrastructure.external_apis.logging_service import redis_logger
from src.backend.infrastructure.resilience.client_breaker import (
    CircuitOpen,
    ClientCircuitBreaker,
)

__all__ = ("redis_client", "RedisClient", "get_redis_client")


RedisKind = Literal["cache", "queue", "limits"]


class RedisClient:
    """Redis-клиент с раздельными подключениями для cache/queue/limits."""

    def __init__(self, settings: RedisSettings) -> None:
        self.settings = settings
        self.logger = redis_logger

        self._clients: dict[RedisKind, Redis | None] = {
            "cache": None,
            "queue": None,
            "limits": None,
        }
        self._locks: dict[RedisKind, asyncio.Lock] = {
            "cache": asyncio.Lock(),
            "queue": asyncio.Lock(),
            "limits": asyncio.Lock(),
        }
        # IL1.4: per-kind CircuitBreaker. При падении Redis (N подряд failures)
        # пул переходит в OPEN — execute() делает fast-fail без лишних
        # reconnect-попыток, пока не пройдёт recovery_timeout. Thresholds —
        # из PoolingProfile defaults (5/30s); в IL2 можно прокинуть из
        # RedisSettings.pooling.
        self._breakers: dict[RedisKind, ClientCircuitBreaker] = {
            kind: ClientCircuitBreaker(
                name=f"redis.{kind}",
                host=f"{settings.host}:{settings.port}",
                failure_threshold=5,
                recovery_timeout=30.0,
            )
            for kind in ("cache", "queue", "limits")
        }

    def _base_url(self) -> str:
        scheme = "rediss" if self.settings.use_ssl else "redis"
        return f"{scheme}://{self.settings.host}:{self.settings.port}"

    def _db_for_kind(self, kind: RedisKind) -> int:
        mapping = {
            "cache": self.settings.db_cache,
            "queue": self.settings.db_queue,
            "limits": self.settings.db_limits,
        }
        return mapping[kind]

    def _build_client(self, kind: RedisKind) -> Redis:
        return Redis.from_url(
            self._base_url(),
            db=self._db_for_kind(kind),
            password=self.settings.password or None,
            encoding=self.settings.encoding,
            socket_timeout=self.settings.socket_timeout,
            socket_connect_timeout=self.settings.socket_connect_timeout,
            socket_keepalive=self.settings.socket_keepalive,
            retry_on_timeout=self.settings.retry_on_timeout,
            max_connections=self.settings.max_connections,
            decode_responses=False,
            health_check_interval=self.settings.health_check_interval,
        )

    @staticmethod
    def decode(value: Any, _depth: int = 0) -> Any:
        if _depth > 50:
            return value
        if isinstance(value, bytes):
            return value.decode()
        if isinstance(value, dict):
            return {
                (k.decode() if isinstance(k, bytes) else k): RedisClient.decode(
                    v, _depth + 1
                )
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            items = [RedisClient.decode(item, _depth + 1) for item in value]
            return type(value)(items)
        return value

    async def _safe_close(self, client: Redis | None) -> None:
        if client is None:
            return
        try:
            await client.aclose()
        except Exception as exc:
            self.logger.warning(
                "Ошибка закрытия Redis-клиента: %s", str(exc), exc_info=True
            )

    async def get_client(self, kind: RedisKind, force_reconnect: bool = False) -> Redis:
        client = self._clients[kind]
        if client is not None and not force_reconnect:
            return client

        async with self._locks[kind]:
            client = self._clients[kind]
            if client is not None and not force_reconnect:
                return client

            if client is not None:
                await self._safe_close(client)

            client = self._build_client(kind)
            await client.ping()  # type: ignore[misc]
            self._clients[kind] = client

            self.logger.info(
                "Инициализирован Redis-клиент kind=%s db=%s",
                kind,
                self._db_for_kind(kind),
            )
            return client

    async def reset_client(self, kind: RedisKind) -> None:
        async with self._locks[kind]:
            client = self._clients[kind]
            self._clients[kind] = None
            await self._safe_close(client)

    async def close(self) -> None:
        for kind in ("cache", "queue", "limits"):
            await self.reset_client(kind)

    async def ensure_connected(self) -> None:
        await self.get_client("cache")
        await self.get_client("queue")
        await self.get_client("limits")

    async def execute(
        self, kind: RedisKind, operation: Callable[[Redis], Awaitable[Any]]
    ) -> Any:
        """Выполнить Redis-операцию с retry и CB (IL1.4).

        Поведение:
          * CircuitOpen → проброс немедленно (fast-fail).
          * RedisError → один reconnect-retry (как раньше); при повторном
            падении breaker поглощает failure и переводит себя в OPEN через
            `failure_threshold` подряд failures.
        """
        breaker = self._breakers[kind]
        try:
            async with breaker.guard():
                client = await self.get_client(kind)
                try:
                    return await operation(client)
                except (RedisConnectionError, RedisTimeoutError, RedisError) as exc:
                    self.logger.warning(
                        "Redis kind=%s недоступен, reconnect: %s", kind, str(exc)
                    )
                    await self.reset_client(kind)
                    client = await self.get_client(kind, force_reconnect=True)
                    return await operation(client)
        except CircuitOpen as exc:
            # CB не считает это «нашей» ошибкой; пробрасываем с понятным
            # сообщением для upstream-логики (retry budget / fallback).
            self.logger.warning("Redis kind=%s CircuitOpen: %s", kind, str(exc))
            raise

    async def check_connection(self, kind: RedisKind) -> bool:
        try:
            client = await self.get_client(kind)
            return bool(await client.ping())  # type: ignore[misc]
        except RedisError:
            return False

    async def cache_get(self, key: str) -> bytes | None:
        return await self.execute("cache", lambda conn: conn.get(key))

    async def cache_set(self, key: str, value: str | bytes, expire: int) -> None:
        await self.execute("cache", lambda conn: conn.setex(key, expire, value))

    async def cache_delete(self, *keys: str) -> int:
        if not keys:
            return 0
        return int(await self.execute("cache", lambda conn: conn.unlink(*keys)))

    async def cache_delete_pattern(self, pattern: str) -> int:
        async def op(conn: Redis) -> int:
            deleted = 0
            batch: list[bytes] = []

            async for key in conn.scan_iter(match=pattern, count=500):
                batch.append(key)
                if len(batch) >= 500:
                    deleted += await conn.unlink(*batch)
                    batch.clear()

            if batch:
                deleted += await conn.unlink(*batch)

            return deleted

        return int(await self.execute("cache", op))

    async def limits_client(self) -> Redis:
        return await self.get_client("limits")

    async def queue_client(self) -> Redis:
        return await self.get_client("queue")

    async def list_cache_keys(self, pattern: str = "*") -> dict[str, list[str]]:
        async def op(conn: Redis) -> dict[str, list[str]]:
            result: list[str] = []
            async for key in conn.scan_iter(match=pattern, count=500):
                result.append(self.decode(key))
            return {"keys": result}

        return await self.execute("cache", op)

    async def get_cache_value(self, key: str) -> dict[str, str | None]:
        value = await self.cache_get(key)
        return {key: self.decode(value) if value is not None else None}

    async def invalidate_cache(self) -> dict[str, str]:
        async def op(conn: Redis) -> dict[str, str]:
            await conn.flushdb()
            return {"status": "Кэш успешно очищен"}

        return await self.execute("cache", op)

    async def _stream_exists(self, stream_name: str) -> bool:
        async def op(conn: Redis) -> bool:
            return await conn.type(stream_name) == b"stream"

        try:
            return bool(await self.execute("queue", op))
        except Exception as exc:
            self.logger.error(
                "Ошибка проверки стрима %s: %s", stream_name, str(exc), exc_info=True
            )
            return False

    async def create_initial_streams(self) -> None:
        for stream in self.settings.streams:
            stream_name = stream["value"]
            try:
                if not await self._stream_exists(stream_name):
                    await self._initialize_stream(stream_name)
                    self.logger.info("Стрим %s инициализирован", stream_name)
            except Exception as exc:
                self.logger.error(
                    "Не удалось инициализировать стрим %s: %s",
                    stream_name,
                    str(exc),
                    exc_info=True,
                )

    async def _initialize_stream(self, stream_name: str) -> None:
        async def op(conn: Redis) -> None:
            xadd_args: dict[str, Any] = {}
            if self.settings.max_stream_len:
                xadd_args["maxlen"] = self.settings.max_stream_len
                xadd_args["approximate"] = self.settings.approximate_trimming_stream

            init_id = await conn.xadd(
                name=stream_name, fields={"__init__": "initial"}, **xadd_args
            )
            await conn.xdel(stream_name, init_id)

            if self.settings.retention_hours_stream:
                retention_ms = self.settings.retention_hours_stream * 3600 * 1000
                minid = str(int(datetime.now(UTC).timestamp() * 1000) - retention_ms)
                await conn.xtrim(name=stream_name, minid=minid, approximate=True)

        await self.execute("queue", op)

    async def stream_publish(
        self,
        stream: str,
        data: dict[str, Any],
        max_len: int | None = None,
        approximate: bool = True,
    ) -> str:
        async def op(conn: Redis) -> str:
            xadd_args: dict[str, Any] = {}
            if max_len is not None:
                xadd_args["maxlen"] = max_len
                xadd_args["approximate"] = approximate

            event_id = await conn.xadd(stream, data, id="*", **xadd_args)
            return str(self.decode(event_id))

        return await self.execute("queue", op)

    async def stream_move(
        self,
        source_stream: str,
        dest_stream: str,
        event_id: str,
        additional_data: dict[str, Any] | None = None,
    ) -> None:
        async def op(conn: Redis) -> None:
            events = await conn.xrange(source_stream, min=event_id, max=event_id)
            if not events:
                raise RedisError(f"Событие {event_id} не найдено в {source_stream}")

            _, event_data = events[0]
            decoded_event = self.decode(event_data)
            decoded_event["moved_at"] = datetime.now(UTC).isoformat()

            if additional_data:
                decoded_event.update(additional_data)

            await conn.xadd(dest_stream, decoded_event, id="*")
            await conn.xdel(source_stream, event_id)

        await self.execute("queue", op)

    async def stream_read(
        self,
        stream: str,
        last_id: str = "$",
        count: int = 100,
        block_ms: int = 5000,
        ack: bool = False,
        consumer_group: tuple[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        async def op(conn: Redis) -> list[dict[str, Any]]:
            if consumer_group:
                group, consumer = consumer_group
                events = await conn.xreadgroup(
                    groupname=group,
                    consumername=consumer,
                    streams={stream: last_id},
                    count=count,
                    block=block_ms,
                )
            else:
                events = await conn.xread(
                    streams={stream: last_id}, count=count, block=block_ms
                )

            result: list[dict[str, Any]] = []
            ack_ids: list[str] = []

            for stream_name, stream_events in events:
                for event_id, event_data in stream_events:
                    decoded_event_id = self.decode(event_id)
                    result.append(
                        {
                            "id": decoded_event_id,
                            "stream": self.decode(stream_name),
                            "data": self.decode(event_data),
                        }
                    )
                    if ack and consumer_group:
                        ack_ids.append(decoded_event_id)

            if ack and consumer_group and ack_ids:
                await conn.xack(stream, consumer_group[0], *ack_ids)

            return result

        return await self.execute("queue", op)

    async def stream_get_stats(
        self, stream: str, num_last_events: int = 5
    ) -> dict[str, Any]:
        async def op(conn: Redis) -> dict[str, Any]:
            return {
                "length": await conn.xlen(stream),
                "last_events": self.decode(
                    await conn.xrevrange(stream, count=num_last_events)
                ),
                "first_event": self.decode(await conn.xrange(stream, count=1)),
                "groups": self.decode(await conn.xinfo_groups(stream)),
            }

        return await self.execute("queue", op)

    async def stream_retry_event(
        self,
        stream: str,
        event_id: str,
        retry_field: str = "retries",
        max_retries: int | None = None,
        ttl_field: str | None = "expires_at",
        ttl: timedelta | None = None,
    ) -> bool:
        async def op(conn: Redis) -> bool:
            events = await conn.xrange(stream, min=event_id, max=event_id)
            if not events:
                return False

            _, event_data = events[0]
            decoded_event = self.decode(event_data)

            retries_limit = (
                max_retries if max_retries is not None else self.settings.max_retries
            )
            current_retries = int(decoded_event.get(retry_field, 0))

            if current_retries >= retries_limit:
                return False

            decoded_event[retry_field] = str(current_retries + 1)

            if ttl and ttl_field:
                decoded_event[ttl_field] = (datetime.now(UTC) + ttl).isoformat()

            await conn.xadd(stream, decoded_event, id="*")
            await conn.xdel(stream, event_id)
            return True

        return await self.execute("queue", op)


@lru_cache(maxsize=1)
def get_redis_client() -> RedisClient:
    """Lazy singleton ``RedisClient`` (Wave 6.1).

    Создаёт ``asyncio.Lock``-и в ``__init__`` — отложено до первого
    обращения, чтобы избежать привязки к event-loop'у времён импорта.
    """
    return RedisClient(settings=settings.redis)


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat ``redis_client``."""
    if name == "redis_client":
        return get_redis_client()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
