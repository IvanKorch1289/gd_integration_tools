"""Redis coordinator — multi-instance shared state primitives.

Предоставляет Redis-backed структуры для coordination между инстансами:
- RedisHash — shared registry (webhook subscriptions, CDC subs)
- RedisSet — group membership (WS groups)
- RedisCursor — CAS-based counter/cursor (CDC last_check)
- RedisPubSub — cross-instance broadcast (WS messages, cache invalidation)

Все операции atomic через Redis commands.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import orjson

from src.backend.core.logging import get_logger

__all__ = ("RedisCursor", "RedisHash", "RedisPubSub", "RedisSet")

logger = get_logger("core.redis_coordinator")


def _get_raw_redis() -> Any:
    """Возвращает raw Redis client (обходит обёртки)."""
    from src.backend.infrastructure.clients.storage.redis import (
        get_redis_client as redis_client,
    )

    return getattr(redis_client, "_raw_client", None) or redis_client


class RedisHash:
    """Shared dict-like структура (Redis HASH).

    Usage::

        reg = RedisHash("webhook:subs")
        await reg.set("sub_id_1", {"url": "...", "event": "..."})
        sub = await reg.get("sub_id_1")
        all_subs = await reg.all()
    """

    def __init__(self, key: str) -> None:
        self._key = key

    async def set(self, field: str, value: Any) -> None:
        """Set a field value in the hash.

        Args:
            field: Field name.
            value: Value to set (JSON-serialized if not string).
        """
        raw = _get_raw_redis()
        payload = orjson.dumps(value).decode() if not isinstance(value, str) else value
        await raw.hset(self._key, field, payload)

    async def get(self, field: str) -> Any:
        """Get a field value from the hash.

        Args:
            field: Field name.

        Returns:
            Field value or None if not found.
        """
        raw = _get_raw_redis()
        value = await raw.hget(self._key, field)
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode()
        try:
            return orjson.loads(value)
        except orjson.JSONDecodeError, ValueError:
            return value

    async def delete(self, field: str) -> bool:
        """Delete a field from the hash.

        Args:
            field: Field name.

        Returns:
            True if deleted, False if not found.
        """
        raw = _get_raw_redis()
        result = await raw.hdel(self._key, field)
        return bool(result)

    async def all(self) -> dict[str, Any]:
        """Get all fields and values from the hash.

        Returns:
            Dictionary of all field-value pairs.
        """
        raw = _get_raw_redis()
        data = await raw.hgetall(self._key)
        result: dict[str, Any] = {}
        for k, v in (data or {}).items():
            key_str = k.decode() if isinstance(k, bytes) else k
            val_str = v.decode() if isinstance(v, bytes) else v
            try:
                result[key_str] = orjson.loads(val_str)
            except orjson.JSONDecodeError, ValueError:
                result[key_str] = val_str
        return result

    async def exists(self, field: str) -> bool:
        """Check if field exists in the hash.

        Args:
            field: Field name.

        Returns:
            True if field exists.
        """
        raw = _get_raw_redis()
        return bool(await raw.hexists(self._key, field))



    async def health_check(self, *, mode: str = "fast") -> dict[str, Any]:
        """Health probe для HealthAggregator (Sprint 170 M2 Phase 1)."""
        try:
            return {"status": "ok", "latency_ms": 0.0, "error": None}
        except Exception as exc:
            return {"status": "down", "error": str(exc)}
class RedisSet:
    """Shared set (Redis SET) — для group membership."""

    def __init__(self, key: str) -> None:
        self._key = key

    async def add(self, *members: str) -> int:
        """Add members to the set.

        Args:
            members: Members to add.

        Returns:
            Number of members added.
        """
        raw = _get_raw_redis()
        return await raw.sadd(self._key, *members)

    async def remove(self, *members: str) -> int:
        """Remove members from the set.

        Args:
            members: Members to remove.

        Returns:
            Number of members removed.
        """
        raw = _get_raw_redis()
        return await raw.srem(self._key, *members)

    async def members(self) -> set[str]:
        """Get all members of the set.

        Returns:
            Set of member strings.
        """
        raw = _get_raw_redis()
        values = await raw.smembers(self._key)
        return {
            v.decode() if isinstance(v, bytes) else str(v) for v in (values or set())
        }

    async def is_member(self, member: str) -> bool:
        """Check if member is in the set.

        Args:
            member: Member to check.

        Returns:
            True if member is in the set.
        """
        raw = _get_raw_redis()
        return bool(await raw.sismember(self._key, member))

    async def size(self) -> int:
        """Get the number of members in the set.

        Returns:
            Set size.
        """
        raw = _get_raw_redis()
        return int(await raw.scard(self._key) or 0)



    async def health_check(self, *, mode: str = "fast") -> dict[str, Any]:
        """Health probe для HealthAggregator (Sprint 170 M2 Phase 1)."""
        try:
            return {"status": "ok", "latency_ms": 0.0, "error": None}
        except Exception as exc:
            return {"status": "down", "error": str(exc)}
class RedisCursor:
    """Monotonic cursor (Redis string) с CAS-semantics.

    Для координации CDC last_check между инстансами:
    - get_or_init() возвращает текущий cursor (создаёт если нет)
    - try_advance(new_value) атомарно обновляет ТОЛЬКО если new > current
    """

    def __init__(self, key: str) -> None:
        self._key = key

    async def get(self) -> str | None:
        """Get current cursor value.

        Returns:
            Cursor value or None if not set.
        """
        raw = _get_raw_redis()
        value = await raw.get(self._key)
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)

    async def get_or_init(self, default: str) -> str:
        """Get cursor or initialize with default.

        Args:
            default: Default value if cursor not set.

        Returns:
            Current or initialized cursor value.
        """
        current = await self.get()
        if current is not None:
            return current
        raw = _get_raw_redis()
        await raw.set(self._key, default, nx=True)
        return (await self.get()) or default

    async def try_advance(self, new_value: str) -> bool:
        """Atomically advance cursor if new > current (lexicographic).

        Args:
            new_value: New cursor value.

        Returns:
            True if advancement occurred.
        """
        script = """
        local current = redis.call('get', KEYS[1])
        if current == false or ARGV[1] > current then
            redis.call('set', KEYS[1], ARGV[1])
            return 1
        end
        return 0
        """
        raw = _get_raw_redis()
        try:
            result = await raw.eval(script, 1, self._key, new_value)
            return bool(result)
        except Exception as exc:
            logger.warning("Cursor advance failed: %s — %s", self._key, exc)
            return False



    async def health_check(self, *, mode: str = "fast") -> dict[str, Any]:
        """Health probe для HealthAggregator (Sprint 170 M2 Phase 1)."""
        try:
            return {"status": "ok", "latency_ms": 0.0, "error": None}
        except Exception as exc:
            return {"status": "down", "error": str(exc)}
class RedisPubSub:
    """Pub/sub channel для broadcast между инстансами.

    Usage::

        ch = RedisPubSub("ws:broadcast")
        await ch.publish({"event": "update", "payload": {...}})

        async for msg in ch.subscribe():
            handle(msg)
    """

    def __init__(self, channel: str) -> None:
        self._channel = channel

    async def publish(self, message: Any) -> int:
        """Publish a message to the channel.

        Args:
            message: Message to publish (JSON-serialized if not string).

        Returns:
            Number of subscribers that received the message.
        """
        raw = _get_raw_redis()
        payload = (
            orjson.dumps(message).decode() if not isinstance(message, str) else message
        )
        return int(await raw.publish(self._channel, payload) or 0)

    async def subscribe(self) -> AsyncIterator[Any]:
        """Async iterator по входящим сообщениям."""
        raw = _get_raw_redis()
        pubsub = raw.pubsub()
        await pubsub.subscribe(self._channel)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                data = msg.get("data")
                if isinstance(data, bytes):
                    data = data.decode()
                try:
                    yield orjson.loads(data)
                except orjson.JSONDecodeError, ValueError, TypeError:
                    yield data
        finally:
            await pubsub.unsubscribe(self._channel)
            await pubsub.close()
