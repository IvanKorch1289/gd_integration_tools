from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.backend.infrastructure.clients.storage.redis._protocol import (
    _RedisClientProtocol,
)
from src.backend.core.logging import get_logger
redis_logger = get_logger("redis")


RedisKind = Literal["cache", "queue", "limits"]


class StreamMixin(_RedisClientProtocol):
    """stream ops (publish, move, read, retry, stats, init, exists) для RedisClient. S59 W3 extraction."""

    __slots__ = ()

    async def _stream_exists(self, stream_name: str) -> bool:
        """Check if Redis stream exists.

        Args:
            stream_name: Stream name.

        Returns:
            True if stream exists.
        """
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
        """Инициализирует Redis Streams из настроек, если они не существуют."""
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
        """Initialize a Redis stream with optional maxlen and retention.

        Args:
            stream_name: Stream name to initialize.
        """
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
        """Публикует событие в Redis Stream.

        Args:
            stream: имя стрима.
            data: поля события.
            max_len: ограничение длины стрима.
            approximate: приблизительное обрезание.

        Returns:
            ID добавленного события.
        """

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
        """Перемещает событие между стримами (копия + удаление).

        Args:
            source_stream: исходный стрим.
            dest_stream: целевой стрим.
            event_id: ID события.
            additional_data: дополнительные поля к событию.
        """

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
        """Читает события из Redis Stream.

        Args:
            stream: имя стрима.
            last_id: начальный ID ("$" — только новые).
            count: максимальное число событий.
            block_ms: таймаут блокировки в мс.
            ack: автоматически подтвердить (ACK) события.
            consumer_group: кортеж (group_name, consumer_name).

        Returns:
            Список событий с id, stream и data.

        """

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
        """Возвращает статистику стрима.

        Args:
            stream: имя стрима.
            num_last_events: число последних событий.

        Returns:
            Словарь с length, last_events, first_event, groups.
        """

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
        """Увеличивает счётчик retries и переписывает событие.

        Args:
            stream: имя стрима.
            event_id: ID события.
            retry_field: имя поля счётчика.
            max_retries: лимит retries (None → из настроек).
            ttl_field: имя поля TTL.
            ttl: timedelta для пересчёта expires_at.

        Returns:
            True если retry разрешён, False если лимит исчерпан.
        """

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
