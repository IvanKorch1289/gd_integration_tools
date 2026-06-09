"""Redis pub/sub broadcaster для feature-flag changes (Sprint 17 K5 W1 / D9).

Multi-replica propagation feature-flag overrides между k8s-репликами через
Redis pub/sub channel ``feature-flags:toggle``. Publish-сторона эмитирует
сериализованный :class:`FeatureFlagChange` после каждого
``RuntimeFeatureFlagOverrides.set`` / ``.clear``. Subscribe-сторона
запускается в lifespan startup как long-running task через
:class:`TaskRegistry` (R-V15-11) и применяет полученные events к local
singleton — без записи в Redis pub/sub loop (избегаем echo).

Поведение
---------

* **Default-OFF** — управление через feature-flag
  ``tenant_feature_flag_ui`` (default-OFF в backbone S17). Если flag
  выключен, ``maybe_start_broadcaster`` возвращает ``None`` и singleton
  работает per-process (как было до S17 K5 W1).
* **Graceful fallback** — при недоступности Redis (connection error)
  broadcaster логирует WARNING и продолжает работу в local-only режиме
  (никогда не валит startup).
* **Echo-detection** — publisher добавляет к payload ``source_replica``
  (UUID процесса). При получении own-event subscriber его игнорирует.

DoD S17 #11 — propagation latency p95 ≤ 100ms (carryover к perf-wave).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import orjson

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from redis.asyncio import Redis as AsyncRedis

    from src.backend.core.feature_flags.runtime_overrides import (
        FeatureFlagChange,
        RuntimeFeatureFlagOverrides,
    )

__all__ = (
    "BROADCAST_CHANNEL",
    "RedisFeatureFlagBroadcaster",
    "deserialize_change",
    "maybe_start_broadcaster",
    "serialize_change",
)

_logger = get_logger("core.feature_flags.redis_broadcaster")

#: Redis pub/sub channel для broadcast feature-flag changes.
BROADCAST_CHANNEL = "feature-flags:toggle"

#: UUID текущего процесса (replica) для echo-detection.
_PROCESS_REPLICA_ID = uuid.uuid4().hex[:16]


def serialize_change(change: FeatureFlagChange) -> bytes:
    """Сериализовать ``FeatureFlagChange`` для Redis publish.

    Args:
        change: Объект изменения из ``RuntimeFeatureFlagOverrides.set/clear``.

    Returns:
        orjson-сериализованный payload с ``source_replica`` для echo-detection.
    """
    payload = {
        "flag": change.flag,
        "tenant_id": change.tenant_id,
        "old_value": change.old_value,
        "new_value": change.new_value,
        "actor": change.actor,
        "timestamp": change.timestamp.isoformat(),
        "source_replica": _PROCESS_REPLICA_ID,
    }
    return orjson.dumps(payload)


def deserialize_change(payload: bytes) -> dict[str, Any]:
    """Распарсить Redis payload в dict (без восстановления datetime)."""
    return orjson.loads(payload)


@dataclass(slots=True)
class _BroadcasterState:
    """Internal состояние broadcaster'а (для тестов и shutdown)."""

    received_total: int = 0
    echo_skipped_total: int = 0
    applied_total: int = 0
    publish_total: int = 0
    publish_errors_total: int = 0


class RedisFeatureFlagBroadcaster:
    """Pub/sub broadcaster для multi-replica feature-flag propagation.

    Args:
        redis_client: Async Redis client (из ``infrastructure/cache/redis``).
        overrides: ``RuntimeFeatureFlagOverrides`` singleton, к которому
            применяются полученные changes.
        channel: Redis pub/sub channel (override для тестов).

    Lifecycle:
        * ``start()`` — запускает subscriber loop через TaskRegistry.
        * ``stop()`` — останавливает subscriber, отписывается от channel.
        * ``publish(change)`` — публикует один FeatureFlagChange.
    """

    def __init__(
        self,
        *,
        redis_client: AsyncRedis,
        overrides: RuntimeFeatureFlagOverrides,
        channel: str = BROADCAST_CHANNEL,
    ) -> None:
        self._redis = redis_client
        self._overrides = overrides
        self._channel = channel
        self._pubsub: Any | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._state = _BroadcasterState()

    @property
    def state(self) -> _BroadcasterState:
        """Снимок counter'ов для health-check и admin endpoints."""
        return self._state

    @property
    def replica_id(self) -> str:
        """UUID текущего процесса (для отладки и echo-detection)."""
        return _PROCESS_REPLICA_ID

    async def publish(self, change: FeatureFlagChange) -> bool:
        """Опубликовать одно изменение в Redis pub/sub channel.

        Returns:
            ``True`` если publish успешен, ``False`` при ошибке Redis.
        """
        try:
            await self._redis.publish(self._channel, serialize_change(change))
            self._state.publish_total += 1
            return True
        except Exception as exc:
            self._state.publish_errors_total += 1
            _logger.warning(
                "feature_flag.broadcast.publish_failed: %s",
                exc,
                extra={"flag": change.flag, "tenant_id": change.tenant_id},
            )
            return False

    async def start(
        self, *, task_factory: Callable[..., asyncio.Task[Any]] | None = None
    ) -> None:
        """Запустить subscriber loop через TaskRegistry.

        Args:
            task_factory: Optional фабрика для тестов. По умолчанию
                используется ``get_task_registry().create_task``.
        """
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(self._channel)
        if task_factory is None:
            from src.backend.core.utils.task_registry import get_task_registry

            task_factory = get_task_registry().create_task
        self._task = task_factory(
            self._listen(), name="feature-flag-broadcaster-subscriber"
        )
        _logger.info(
            "feature_flag.broadcast.subscriber.started",
            extra={"channel": self._channel, "replica_id": _PROCESS_REPLICA_ID},
        )

    async def stop(self) -> None:
        """Graceful shutdown — отписаться и отменить subscriber task."""
        self._stop_event.set()
        if self._pubsub is not None:
            try:
                await self._pubsub.unsubscribe(self._channel)
                await self._pubsub.aclose()
            except Exception as exc:
                _logger.debug("feature_flag.broadcast.unsubscribe_error: %s", exc)
            self._pubsub = None
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                _logger.debug("feature_flag.broadcast.subscriber.stop_error: %s", exc)
            self._task = None
        _logger.info("feature_flag.broadcast.subscriber.stopped")

    async def _listen(self) -> None:
        """Subscriber loop: получает messages и применяет к local singleton."""
        if self._pubsub is None:  # pragma: no cover — start() гарантирует
            return
        try:
            async for message in self._pubsub.listen():
                if self._stop_event.is_set():
                    break
                if message is None or message.get("type") != "message":
                    continue
                self._apply_message(message.get("data"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.warning("feature_flag.broadcast.subscriber.listen_error: %s", exc)

    def _apply_message(self, raw: Any) -> None:
        """Распарсить и применить одно сообщение из pub/sub channel."""
        if raw is None:
            return
        payload_bytes = (
            raw if isinstance(raw, (bytes, bytearray)) else str(raw).encode()
        )
        try:
            payload = deserialize_change(payload_bytes)
        except orjson.JSONDecodeError as exc:
            _logger.warning("feature_flag.broadcast.malformed_payload: %s", exc)
            return
        self._state.received_total += 1
        if payload.get("source_replica") == _PROCESS_REPLICA_ID:
            self._state.echo_skipped_total += 1
            return
        flag = payload.get("flag")
        if not flag:
            _logger.warning("feature_flag.broadcast.missing_flag", extra=payload)
            return
        tenant_id = payload.get("tenant_id")
        new_value = payload.get("new_value")
        actor = payload.get("actor", "broadcast")
        if new_value is None:
            # Это clear (snapshot — pop)
            self._overrides.clear(flag, tenant_id=tenant_id)
        else:
            self._overrides.set(
                flag, new_value, tenant_id=tenant_id, actor=f"broadcast:{actor}"
            )
        self._state.applied_total += 1
        _logger.debug(
            "feature_flag.broadcast.applied",
            extra={"flag": flag, "tenant_id": tenant_id, "new_value": new_value},
        )


async def maybe_start_broadcaster(
    *, redis_client: AsyncRedis | None, overrides: RuntimeFeatureFlagOverrides
) -> RedisFeatureFlagBroadcaster | None:
    """Запустить broadcaster, если feature-flag ``tenant_feature_flag_ui=True``.

    Args:
        redis_client: Async Redis client (``None`` → graceful no-op).
        overrides: Singleton runtime overrides.

    Returns:
        Запущенный broadcaster или ``None`` (flag выключен / Redis недоступен).
    """
    try:
        from src.backend.core.config.features import feature_flags
    except ImportError:
        return None
    if not getattr(feature_flags, "tenant_feature_flag_ui", False):
        _logger.info(
            "feature_flag.broadcast.skipped",
            extra={"reason": "tenant_feature_flag_ui=False"},
        )
        return None
    if redis_client is None:
        _logger.warning(
            "feature_flag.broadcast.skipped", extra={"reason": "redis_client is None"}
        )
        return None
    broadcaster = RedisFeatureFlagBroadcaster(
        redis_client=redis_client, overrides=overrides
    )
    try:
        await broadcaster.start()
    except Exception as exc:
        _logger.warning(
            "feature_flag.broadcast.start_failed: %s",
            exc,
            extra={"replica_id": _PROCESS_REPLICA_ID},
        )
        return None
    return broadcaster


def _now_utc() -> datetime:
    """Wrapper для тестов (timestamp override)."""
    return datetime.now(UTC)


# Чтобы unit-тесты могли подменить replica_id (тест cross-replica scenario).
def _set_replica_id_for_tests(value: str) -> str:
    """**Только для тестов**: подменить ``_PROCESS_REPLICA_ID``."""
    global _PROCESS_REPLICA_ID
    previous = _PROCESS_REPLICA_ID
    _PROCESS_REPLICA_ID = value
    return previous


# Force fresh UUID при reload модуля (тесты делают reset).
if os.getenv("PYTEST_CURRENT_TEST"):
    _PROCESS_REPLICA_ID = uuid.uuid4().hex[:16]
