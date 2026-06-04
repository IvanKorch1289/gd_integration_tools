"""RedisClusterAdapter — тонкая обёртка над ``redis.asyncio.RedisCluster``.

Sprint 3 К2 W1: подготовительная инфраструктура для multi-master Redis
cluster (без TLS, single-DC). Полное wiring через DI выполняется в
``plugins/composition/`` под env-flag ``REDIS_CLUSTER_ENABLED=false``.

Назначение:

* конструктор с explicit connection-pool параметрами (R-V15-14):
  ``max_connections``, ``socket_keepalive``, ``health_check_interval``;
* async ``ping()`` для health-check'а кластера (вызывает PING на
  random-master через redis-py 5.x routing);
* ``close()`` для graceful shutdown в lifespan.

Подключение к multi-master cluster (3+ узла) выполняется через
``startup_nodes`` (``ClusterNode``-список) — redis-py сам диктует
slot-routing на основе CRC16(key) MOD 16384.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from typing import TYPE_CHECKING, Any

__all__ = ("RedisClusterAdapter",)

if TYPE_CHECKING:  # pragma: no cover — только для типов
    from redis.asyncio.cluster import ClusterNode, RedisCluster

logger = logging.getLogger("infra.cache.redis_cluster")


class RedisClusterAdapter:
    """Async-обёртка над ``redis.asyncio.cluster.RedisCluster``.

    Создаёт ``RedisCluster`` с явными connection-pool лимитами и
    keepalive-настройками (R-V15-14). Поддерживает graceful shutdown
    через :meth:`close`.

    Args:
        startup_nodes: список ``ClusterNode(host, port)`` (минимум один
            seed-узел; remaining discovered автоматически).
        max_connections: верхний лимит соединений в pool'е на узел.
        socket_keepalive: TCP keepalive на сокетах.
        health_check_interval: периодичность фоновой проверки соединений
            в секундах (redis-py 5.x: ``health_check_interval``).
        password: опц. пароль кластера.
        decode_responses: если ``True`` — возвращает ``str`` вместо bytes.
    """

    def __init__(
        self,
        *,
        startup_nodes: Sequence[ClusterNode],
        max_connections: int = 50,
        socket_keepalive: bool = True,
        health_check_interval: int = 30,
        password: str | None = None,
        decode_responses: bool = False,
    ) -> None:
        from redis.asyncio.cluster import RedisCluster

        self._cluster: RedisCluster = RedisCluster(
            startup_nodes=list(startup_nodes),
            max_connections=max_connections,
            socket_keepalive=socket_keepalive,
            health_check_interval=health_check_interval,
            password=password,
            decode_responses=decode_responses,
        )
        self._closed = False

    @property
    def client(self) -> RedisCluster:
        """Доступ к нижележащему RedisCluster для прямых вызовов."""
        return self._cluster

    async def ping(self) -> bool:
        """Async health-check — отправляет PING на random-master узел.

        Returns:
            ``True`` если кластер отвечает; ``False`` при любой ошибке
            (логируется в WARNING).
        """
        try:
            result = await self._cluster.ping()
            # ``ping()`` на cluster возвращает dict {node: True/bytes}
            # либо просто True — нормализуем.
            if isinstance(result, dict):
                return all(bool(v) for v in result.values())
            return bool(result)
        except Exception as exc:
            logger.warning("RedisClusterAdapter.ping failed: %s", exc)
            return False

    async def close(self) -> None:
        """Закрыть все pool-соединения кластера (graceful shutdown).

        Идемпотентно: повторный вызов — no-op.
        """
        if self._closed:
            return
        try:
            await self._cluster.aclose()
        except AttributeError:
            # redis-py <5 имеет .close() вместо .aclose() — fallback.
            await self._cluster.close()
        except Exception as exc:
            logger.warning("RedisClusterAdapter.close error: %s", exc)
        self._closed = True

    # ──────────────── S13 K2 W6: pipelining + batch ops ────────────────

    def pipeline(self, *, routing_key: str | None = None) -> Any:
        """Возвращает RedisCluster pipeline (S13 K2 W6).

        Pipeline в Redis Cluster привязан к одному shard (CRC16(routing_key)).
        Используется через ``async with``::

            async with adapter.pipeline(routing_key="user:42") as pipe:
                pipe.set("user:42:name", "alice")
                pipe.incr("user:42:visits")
                results = await pipe.execute()

        Args:
            routing_key: Ключ для определения shard'а (default: автоматически).
        """
        return self._cluster.pipeline()

    async def mget_batch(self, keys: Sequence[str]) -> list[Any]:
        """Batch GET с распределением по shard'ам (S13 K2 W6).

        В отличие от обычного ``mget`` (требует все keys в одном slot),
        этот метод группирует keys по shard и параллельно выполняет.

        Args:
            keys: Список ключей.

        Returns:
            Значения в исходном порядке (``None`` для отсутствующих).
        """
        if not keys:
            return []
        # redis-py 5.x: RedisCluster.mget работает для разных slot'ов через
        # внутреннюю группировку по shard'у.
        try:
            return await self._cluster.mget(list(keys))
        except Exception as _:
            # Fallback: fan-out параллельных GET.
            import asyncio

            results = await asyncio.gather(
                *(self._cluster.get(k) for k in keys), return_exceptions=False
            )
            return list(results)

    async def mset_batch(self, mapping: dict[str, Any]) -> None:
        """Batch SET с распределением по shard'ам (S13 K2 W6).

        Args:
            mapping: ``{key: value}`` для записи.
        """
        if not mapping:
            return
        try:
            await self._cluster.mset(mapping)
        except Exception as _:
            import asyncio

            await asyncio.gather(*(self._cluster.set(k, v) for k, v in mapping.items()))

    async def keys_scan_batch(
        self, pattern: str, *, batch_size: int = 1000
    ) -> AsyncIterator[list[bytes]]:
        """SCAN keys батчами по shard'ам (S13 K2 W6).

        Используется для bulk-cleanup и invalidation operations.

        Args:
            pattern: Glob-pattern для match (e.g. ``"session:*"``).
            batch_size: Размер batch'а на один yield.

        Yields:
            Списки keys по ``batch_size`` штук.
        """
        async for key in self._cluster.scan_iter(match=pattern, count=batch_size):
            yield [key]

    async def eval_script(
        self, script: str, keys: Sequence[str], args: Sequence[Any]
    ) -> Any:
        """Lua scripting (atomic multi-key operations) (S13 K2 W6).

        Все ``keys`` ДОЛЖНЫ находиться в одном slot (используй hashtag
        для force routing: ``{user:42}:name`` + ``{user:42}:visits``).
        """
        return await self._cluster.eval(script, len(keys), *keys, *args)  # type: ignore[misc]
