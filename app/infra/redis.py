from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import asyncio
from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from app.config.settings import RedisSettings, settings
from app.utils.decorators.singleton import singleton
from app.utils.logging_service import redis_logger
from app.utils.utils import utilities


__all__ = ("redis_client", "RedisClient")


@singleton
class RedisClient:
    """Async Redis client wrapper with connection pooling and automatic reconnection.

    Attributes:
        settings: Redis configuration settings
        _client: Redis async client instance
        _lock: Asyncio lock for thread-safe connection initialization
        _connection_pool: Redis connection pool manager
    """

    def __init__(self, settings: RedisSettings) -> None:
        """Initialize Redis client with configuration settings.

        Args:
            settings: Redis configuration parameters
        """
        self._client: Optional[Redis] = None
        self._lock = asyncio.Lock()
        self.settings = settings
        self._connection_pool: Optional[ConnectionPool] = None
        self.logger = redis_logger

    async def _init_pool(self) -> None:
        """Initialize Redis connection pool with configured parameters."""
        # Build Redis connection URL based on SSL configuration
        redis_scheme = "rediss" if self.settings.use_ssl else "redis"
        redis_url = (
            f"{redis_scheme}://{self.settings.host}:{self.settings.port}"
        )

        try:
            self._connection_pool = ConnectionPool.from_url(
                redis_url,
                db=self.settings.db_cache,
                password=self.settings.password or None,
                encoding=self.settings.encoding,
                socket_timeout=self.settings.socket_timeout,
                socket_connect_timeout=self.settings.socket_connect_timeout,
                socket_keepalive=self.settings.socket_keepalive,
                retry_on_timeout=self.settings.retry_on_timeout,
                max_connections=self.settings.max_connections,
                decode_responses=False,
            )

            self._client = Redis(connection_pool=self._connection_pool)
            self.logger.info("Redis connection pool initialized successfully")
        except RedisError:
            self.logger.error(
                "Connection pool initialization failed", exc_info=True
            )
            raise

    async def ensure_connected(self) -> None:
        """Ensure active connection exists using double-checked locking pattern."""
        if self._client and await self._client.ping():
            return

        async with self._lock:
            if not self._client or not await self._client.ping():
                await self._init_pool()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[Redis]:
        """Async context manager for Redis connections.

        Yields:
            Redis: Active Redis connection instance

        Raises:
            RedisError: If connection cannot be established
        """
        await self.ensure_connected()
        try:
            if not self._client:
                raise RedisError("Redis client not initialized")

            yield self._client
        except (RedisError, ConnectionError, TimeoutError) as exc:
            self.logger.error("Redis connection error", exc_info=True)
            await self.close()
            raise RedisError(f"Connection failed: {str(exc)}") from exc

    async def close(self) -> None:
        """Close all Redis connections and clean up resources."""
        if self._connection_pool:
            try:
                await self._connection_pool.disconnect()
                self.logger.info("Redis connection pool closed successfully")
            except Exception:
                self.logger.error(
                    "Error closing connection pool", exc_info=True
                )
            finally:
                self._client = None
                self._connection_pool = None

    async def check_connection(self) -> bool:
        """Check if Redis connection is alive.

        Returns:
            bool: True if connection is active, False otherwise
        """
        try:
            async with self.connection() as conn:
                return await conn.ping()
        except RedisError:
            return False

    def reconnect_on_failure(self, func: Any) -> Any:
        """Decorator to automatically reconnect on connection failures.

        Args:
            func: Method to wrap with reconnection logic
        """

        @wraps(func)
        async def wrapper(
            self: "RedisClient", *args: Any, **kwargs: Any
        ) -> Any:
            try:
                return await func(self, *args, **kwargs)
            except (ConnectionError, TimeoutError, RedisError) as e:
                self.logger.warning(f"Reconnecting due to error: {str(e)}")
                await self.close()
                await self.ensure_connected()
                return await func(self, *args, **kwargs)

        return wrapper

    async def __aenter__(self) -> "RedisClient":
        """Async context manager entry point."""
        await self.ensure_connected()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        """Async context manager exit point."""
        await self.close()

    async def stream_publish(
        self,
        stream: str,
        data: Dict[str, Any],
        max_len: Optional[int] = None,
        approximate: bool = True,
    ) -> str:
        """Publish event to Redis stream.

        Args:
            stream: Target stream name
            data: Event data dictionary
            max_len: Optional maximum stream length (for trimming)
            approximate: Use efficient trimming with ~ precision

        Returns:
            Generated event ID

        Raises:
            RedisError: If publishing fails
        """
        try:
            async with self.connection() as conn:
                args = {}
                if max_len is not None:
                    args["maxlen"] = max_len
                    args["approximate"] = approximate

                event_id = await conn.xadd(stream, data, id="*", **args)
                self.logger.debug(f"Event published to {stream}: {event_id}")
                return event_id
        except RedisError:
            self.logger.error("Stream publish failed", exc_info=True)
            raise

    async def stream_move(
        self,
        source_stream: str,
        dest_stream: str,
        event_id: str,
        additional_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Move event between streams with optional metadata.

        Args:
            source_stream: Source stream name
            dest_stream: Destination stream name
            event_id: Event ID to move
            additional_data: Extra data to add to moved event

        Raises:
            RedisError: If operation fails
        """
        try:
            async with self.connection() as conn:
                # Get event data
                events = await conn.xrange(
                    source_stream, min=event_id, max=event_id
                )
                if not events:
                    raise RedisError(
                        f"Event {event_id} not found in {source_stream}"
                    )

                _, event_data = events[0]

                # Add metadata
                event_data["moved_at"] = datetime.now().isoformat()
                if additional_data:
                    event_data.update(additional_data)

                # Write to destination and delete from source
                await conn.xadd(dest_stream, event_data, id="*")
                await conn.xdel(source_stream, event_id)
                self.logger.debug(
                    f"Moved event {event_id} from {source_stream} to {dest_stream}"
                )
        except RedisError:
            self.logger.error("Stream move failed", exc_info=True)
            raise

    async def stream_read(
        self,
        stream: str,
        last_id: str = "$",
        count: int = 100,
        block_ms: int = 5000,
        ack: bool = False,
        consumer_group: Optional[Tuple[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Read events from stream with optional consumer group support.

        Args:
            stream: Stream name to read from
            last_id: Last received event ID
            count: Maximum number of events to return
            block_ms: Blocking time in milliseconds
            ack: Auto-ACK messages after reading
            consumer_group: Tuple of (group, consumer) names

        Returns:
            List of events with metadata

        Raises:
            RedisError: If reading fails
        """
        try:
            async with self.connection() as conn:
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

                result = []
                for _, stream_events in events:
                    for event_id, event_data in stream_events:
                        entry = {
                            "id": event_id,
                            "stream": stream,
                            "data": event_data,
                        }
                        if ack and consumer_group:
                            await conn.xack(
                                stream, consumer_group[0], event_id
                            )
                        result.append(entry)

                return result
        except RedisError:
            self.logger.error("Stream read failed", exc_info=True)
            raise

    async def stream_get_stats(
        self, stream: str, num_last_events: int = 5
    ) -> Dict[str, Any]:
        """Get stream statistics and recent events.

        Args:
            stream: Stream name to analyze
            num_last_events: Number of last events to return

        Returns:
            Dictionary with stream statistics

        Raises:
            RedisError: If operation fails
        """
        try:
            async with self.connection() as conn:
                return {
                    "length": await conn.xlen(stream),
                    "last_events": await conn.xrevrange(
                        stream, count=num_last_events
                    ),
                    "first_event": await conn.xrange(stream, count=1),
                    "groups": await conn.xinfo_groups(stream),
                }
        except RedisError:
            self.logger.error("Stream stats failed", exc_info=True)
            raise

    async def stream_retry_event(
        self,
        stream: str,
        event_id: str,
        retry_field: str = "retries",
        max_retries: int = settings.redis.max_retries,
        ttl_field: Optional[str] = "expires_at",
        ttl: Optional[timedelta] = None,
    ) -> bool:
        """Retry event with updated metadata.

        Args:
            stream: Target stream name
            event_id: Event ID to retry
            retry_field: Field name for retry counter
            max_retries: Maximum allowed retries
            ttl_field: Optional field name for TTL
            ttl: Optional new TTL duration

        Returns:
            True if retry succeeded, False if max retries reached

        Raises:
            RedisError: If operation fails
        """
        try:
            async with self.connection() as conn:
                events = await conn.xrange(stream, min=event_id, max=event_id)
                if not events:
                    return False

                _, event_data = events[0]

                event_data = await utilities.decode_redis_data(
                    redis_data=event_data
                )

                current_retries = int(event_data.get(retry_field, 0))

                if current_retries > max_retries:
                    return False

                event_data[retry_field] = str(current_retries + 1)

                if ttl and ttl_field:
                    event_data[ttl_field] = (datetime.now() + ttl).isoformat()

                await conn.xadd(stream, event_data, id="*")
                await conn.xdel(stream, event_id)
                return True
        except RedisError:
            self.logger.error("Event retry failed", exc_info=True)
            raise


# Singleton instance for application-wide use
redis_client = RedisClient(settings=settings.redis)
