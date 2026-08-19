"""RedisHitlSignalStore — Redis-backed реализация :class:`HitlSignalStore` (S207).

Закрывает Gap#2: HITL cross-instance coordination. До S207 единственной
реализацией был :class:`InMemoryHitlSignalStore` — работал только в
одном процессе. Production с несколькими worker'ами не мог разделять
state между instance'ами.

Использует:
* Redis hash ``hitl:signals`` для persistent state (signal_id → JSON).
* Существующий pub/sub channel ``hitl:resolved:{tenant_id}``
  (:mod:`hitl_pubsub`) для cross-instance ``wait_for()`` уведомлений.

Ponytail: thin wrapper над Redis + existing pubsub. Без новых абстракций.
Lazy-import ``get_redis_client`` — unit-тесты могут подменить через
``fakeredis`` или mock.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, cast

from redis.exceptions import WatchError

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.services.workflows.hitl_service import HitlPendingSignal


class _HitlRedisClient(Protocol):
    """Async Redis surface used by the HITL signal store."""

    async def hset(self, name: str, key: str, value: str) -> int: ...

    async def hget(self, name: str, key: str) -> str | bytes | None: ...

    async def hgetall(self, name: str) -> dict[Any, Any]: ...

    async def publish(self, channel: str, message: str) -> int: ...

    def pipeline(self, *, transaction: bool) -> Any: ...

    def pubsub(self) -> Any: ...


__all__ = ("RedisHitlSignalStore",)

_logger = get_logger("services.workflows.hitl_signal_store_redis")

_HASH_KEY = "hitl:signals"

# D-A8-11 fix (cycle 1): default cap для WATCH retry-loop.
# Persistent contention приводит к tight loop → CPU saturation (DoS vector).
_MAX_WATCH_RETRIES_DEFAULT: int = 10


# D-A8-11 fix (cycle 1): explicit exception при persistent contention.
class HITLWatchContentionError(RuntimeError):
    """Raised when WATCH conflict exceeds max_watch_retries (D-A8-11 cycle 1).

    Persistent contention = tight loop без progress → CPU saturation.
    Caller должен retry с backoff или escalate.
    """


class RedisHitlSignalStore:
    """S207: Redis-backed реализация :class:`HitlSignalStore` для multi-instance.

    State layout:
        Redis hash ``hitl:signals``: field=signal_id, value=JSON (signal dict).
        Cross-instance ``wait_for()`` через existing pub/sub channel
        ``hitl:resolved:{tenant_id}`` (publish делает ``hitl_pubsub.publish_hitl_resolved``).

    Args:
        redis_client: Optional redis.asyncio.Redis instance (для тестов с fakeredis).
            Если None — lazy ``get_redis_client().get_client(RedisKind.QUEUE)``.

    Notes:
        * mark_resolved — атомарный Lua-script (HSETNX + проверка is_resolved)
          для защиты от race conditions между instance'ами. Без скрипта две
          instance'ы могут одновременно сделать resolved → lost update.
        * wait_for — subscribe на ``hitl:resolved:{tenant_id}`` канал с
          фильтром по ``signal_id`` (через payload JSON).

    """

    def __init__(
        self,
        redis_client: _HitlRedisClient | None = None,
        *,
        max_watch_retries: int = _MAX_WATCH_RETRIES_DEFAULT,
    ) -> None:
        """Конструктор RedisHitlSignalStore.

        Args:
            redis_client: Optional redis client (для тестов с fakeredis).
                Если None — lazy ``get_redis_client().get_client(RedisKind.QUEUE)``.
            max_watch_retries: D-A8-11 fix (cycle 1): max retries для WATCH
                conflict в _mark_resolved_transactional. Persistent
                contention → HITLWatchContentionError.

        """
        self._client = redis_client
        self._owns_client = redis_client is None
        self._max_watch_retries = max_watch_retries

    async def _get_client(self) -> _HitlRedisClient:
        """Lazy resolve redis client (для unit-тестов — inject через ctor)."""
        if self._client is not None:
            return self._client
        from src.backend.core.di.providers.infrastructure_locator import (
            get_redis_client_factory,
        )

        get_redis_client = get_redis_client_factory()
        self._client = cast(
            _HitlRedisClient, await get_redis_client().get_client("queue")
        )
        return self._client

    async def put(self, signal: HitlPendingSignal) -> None:
        """Store signal в Redis hash.

        Args:
            signal: Signal для сохранения.

        """
        client = await self._get_client()
        await client.hset(_HASH_KEY, signal.signal_id, json.dumps(signal.to_dict()))

    async def get(self, signal_id: str) -> HitlPendingSignal | None:
        """Получить signal по ID.

        Args:
            signal_id: Signal identifier.

        Returns:
            Signal или None если не найден.

        """
        from src.backend.services.workflows.hitl_service import HitlPendingSignal

        client = await self._get_client()
        raw = await client.hget(_HASH_KEY, signal_id)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return HitlPendingSignal.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            _logger.warning(
                "RedisHitlSignalStore.get failed for signal_id=%s: %s", signal_id, exc
            )
            return None

    async def list_pending(
        self, *, tenant_id: str | None = None
    ) -> list[HitlPendingSignal]:
        """List pending (unresolved) signals.

        Args:
            tenant_id: Optional tenant filter (filter in Python, не indexed — для v1 OK).

        Returns:
            Sorted список unresolved signals.

        """
        from src.backend.services.workflows.hitl_service import HitlPendingSignal

        client = await self._get_client()
        raw_items = await client.hgetall(_HASH_KEY)
        items: list[HitlPendingSignal] = []
        for raw in raw_items.values():
            try:
                data = json.loads(raw)
                sig = HitlPendingSignal.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            if sig.is_resolved:
                continue
            if tenant_id is not None and sig.tenant_id != tenant_id:
                continue
            items.append(sig)
        items.sort(key=lambda s: s.created_at)
        return items

    async def mark_resolved(
        self, signal_id: str, *, action: str, resolved_by: str
    ) -> HitlPendingSignal:
        """Mark signal as resolved (атомарно через Lua).

        Args:
            signal_id: Signal identifier.
            action: Resolution action.
            resolved_by: Resolver identity.

        Returns:
            Updated signal.

        Raises:
            KeyError: Signal не найден.
            ValueError: Signal уже resolved.

        """
        from src.backend.services.workflows.hitl_service import HitlPendingSignal

        client = await self._get_client()
        pipeline_factory = getattr(client, "pipeline", None)
        if pipeline_factory is None:
            data = await self._mark_resolved_without_pipeline(
                client, signal_id, action=action, resolved_by=resolved_by
            )
        else:
            data = await self._mark_resolved_transactional(
                client, signal_id, action=action, resolved_by=resolved_by
            )
        # Cross-instance notify через существующий pub/sub.
        try:
            await client.publish(
                f"hitl:resolved:{data['tenant_id']}",
                json.dumps({"signal_id": signal_id, "action": action}),
            )
        except Exception as exc:
            _logger.warning("publish on mark_resolved failed: %s", exc)
        return HitlPendingSignal.from_dict(data)

    async def _mark_resolved_without_pipeline(
        self, client: _HitlRedisClient, signal_id: str, *, action: str, resolved_by: str
    ) -> dict[str, Any]:
        """Fallback for lightweight Redis test doubles without transactions."""
        raw = await client.hget(_HASH_KEY, signal_id)
        if raw is None:
            raise KeyError(f"HITL signal {signal_id!r} not found in Redis")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError("HITL signal payload must be a JSON object")
        if data.get("resolved_at"):
            raise ValueError(
                f"HITL signal {signal_id!r} already resolved by "
                f"{data.get('resolved_by')!r} as {data.get('resolved_action')!r}"
            )
        data["resolved_at"] = datetime.now(UTC).isoformat()
        data["resolved_action"] = action
        data["resolved_by"] = resolved_by
        data["is_resolved"] = True
        await client.hset(_HASH_KEY, signal_id, json.dumps(data))
        return data

    async def _mark_resolved_transactional(
        self, client: _HitlRedisClient, signal_id: str, *, action: str, resolved_by: str
    ) -> dict[str, Any]:
        """Atomic WATCH/MULTI update for the production Redis client.

        D-A8-11 fix (cycle 1): iteration cap для WATCH retry-loop. Ранее
        bare 'while True: ... continue' без cap → persistent contention
        приводил к tight loop → CPU saturation (DoS vector). Теперь:
        max_watch_retries (default 10) → raise HITLWatchContentionError
        при превышении.
        """
        async with client.pipeline(transaction=True) as pipe:
            data: dict[str, Any] = {}
            watch_attempts = 0
            while True:
                try:
                    watch_attempts += 1
                    if watch_attempts > self._max_watch_retries:
                        # D-A8-11 fix (cycle 1): explicit fail после max_watch_retries.
                        raise HITLWatchContentionError(
                            f"HITL signal {signal_id!r} WATCH conflict exceeded "
                            f"{self._max_watch_retries} retries — persistent contention. "
                            f"Caller must retry или escalate."
                        )
                    await pipe.watch(_HASH_KEY)
                    raw = await pipe.hget(_HASH_KEY, signal_id)
                    if raw is None:
                        await pipe.unwatch()
                        raise KeyError(f"HITL signal {signal_id!r} not found in Redis")
                    decoded = json.loads(raw)
                    if not isinstance(decoded, dict):
                        await pipe.unwatch()
                        raise TypeError("HITL signal payload must be a JSON object")
                    data = decoded
                    if data.get("resolved_at"):
                        await pipe.unwatch()
                        raise ValueError(
                            f"HITL signal {signal_id!r} already resolved by "
                            f"{data.get('resolved_by')!r} as {data.get('resolved_action')!r}"
                        )
                    data["resolved_at"] = datetime.now(UTC).isoformat()
                    data["resolved_action"] = action
                    data["resolved_by"] = resolved_by
                    data["is_resolved"] = True
                    pipe.multi()
                    pipe.hset(_HASH_KEY, signal_id, json.dumps(data))
                    await pipe.execute()
                    return data
                except asyncio.CancelledError:
                    raise
                except (KeyError, TypeError, ValueError):
                    raise
                except WatchError:
                    # WATCH conflict → retry the compare-and-set transaction.
                    continue

    async def wait_for(self, signal_id: str, timeout: float | None = None) -> bool:
        """Ждать разрешения signal через Redis pub/sub (multi-instance).

        Args:
            signal_id: Signal identifier.
            timeout: Optional timeout (seconds).

        Returns:
            True если resolved, False при timeout.

        """
        client = await self._get_client()
        # Сначала проверяем текущее состояние (resolved до подписки).
        existing = await self.get(signal_id)
        if existing is not None and existing.is_resolved:
            return True
        # Subscribe на ВСЕ tenant channels (pattern subscribe), фильтруем
        # по signal_id в payload. Это покрывает cross-tenant listener use case
        # без необходимости знать tenant_id.
        # D-AUDIT-20816 (cycle 225): \`await\` — RedisClient.pubsub() is async
        # (cycle 225 fix). Caller должен await coroutine.
        pubsub = await client.pubsub()
        await pubsub.psubscribe("hitl:resolved:*")
        try:
            deadline = time.monotonic() + timeout if timeout else None
            while True:
                remaining = (
                    deadline - time.monotonic() if deadline is not None else None
                )
                if remaining is not None and remaining <= 0:
                    return False
                try:
                    msg = await asyncio.wait_for(
                        pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=remaining or 30
                        ),
                        timeout=remaining,
                    )
                except TimeoutError:
                    return False
                if msg is None:
                    continue
                try:
                    payload = json.loads(msg.get("data") or "{}")
                except (TypeError, json.JSONDecodeError):
                    continue
                if payload.get("signal_id") == signal_id:
                    return True
        finally:
            try:
                await pubsub.punsubscribe("hitl:resolved:*")
                await pubsub.aclose()
            except (
                OSError,
                ConnectionError,
                RuntimeError,
                AttributeError,
            ) as pubsub_exc:
                # cycle-9/D-AUDIT-911: narrow exceptions + observability.
                # OSError/ConnectionError — network при punsubscribe/aclose,
                # RuntimeError — pubsub не subscribed, AttributeError —
                # API changed. Bare `except Exception` маскировал unrelated
                # runtime errors (KeyError, TypeError).
                import logging

                logging.getLogger(__name__).debug(
                    "hitl_signal_store_redis.pubsub_cleanup_failed",
                    extra={"error": str(pubsub_exc)},
                )
