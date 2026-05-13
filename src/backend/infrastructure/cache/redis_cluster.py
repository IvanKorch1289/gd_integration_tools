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
from collections.abc import Sequence
from typing import TYPE_CHECKING

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
        except Exception as exc:  # noqa: BLE001
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
        except Exception as exc:  # noqa: BLE001
            logger.warning("RedisClusterAdapter.close error: %s", exc)
        self._closed = True
