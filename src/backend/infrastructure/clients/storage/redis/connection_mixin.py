from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from typing import Literal

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.backend.infrastructure.logging.factory import get_logger

redis_logger = get_logger("redis")


RedisKind = Literal["cache", "queue", "limits"]


class ConnectionMixin:
    """connection lifecycle (_build_client, get_client, reset, close, ensure/check) для RedisClient. S59 W3 extraction."""

    __slots__ = ()

    def _build_client(self, kind: RedisKind) -> Redis:
        # Cluster-режим: один общий клиент для всех kinds (cluster
        # использует единую логическую БД, ``db_*`` игнорируются).
        # Лениво импортируем cluster-модуль, чтобы не тянуть его при
        # стандартном single-node варианте.
        retry_on_error = self._resolve_retry_on_error()
        if self.settings.cluster_mode:
            from redis.asyncio.cluster import ClusterNode, RedisCluster

            startup_nodes: list[ClusterNode] = []
            for raw in self.settings.cluster_nodes:
                host, _, port = raw.rpartition(":")
                startup_nodes.append(ClusterNode(host=host, port=int(port)))

            self.logger.info(
                "Инициализация RedisCluster kind=%s nodes=%s",
                kind,
                [f"{n.host}:{n.port}" for n in startup_nodes],
            )
            return RedisCluster(
                startup_nodes=startup_nodes,
                password=self.settings.password or None,
                encoding=self.settings.encoding,
                socket_timeout=self.settings.socket_timeout,
                socket_connect_timeout=self.settings.socket_connect_timeout,
                socket_keepalive=bool(self.settings.socket_keepalive),
                max_connections=self.settings.max_connections,
                decode_responses=False,
                health_check_interval=self.settings.health_check_interval,
                retry_on_error=retry_on_error or None,
                ssl=self.settings.use_ssl,
                ssl_ca_certs=self.settings.ca_bundle,
            )

        return Redis.from_url(
            self._base_url(),
            db=self._db_for_kind(kind),
            password=self.settings.password or None,
            encoding=self.settings.encoding,
            socket_timeout=self.settings.socket_timeout,
            socket_connect_timeout=self.settings.socket_connect_timeout,
            socket_keepalive=self.settings.socket_keepalive,
            retry_on_timeout=self.settings.retry_on_timeout,
            retry_on_error=retry_on_error or None,
            max_connections=self.settings.max_connections,
            decode_responses=False,
            health_check_interval=self.settings.health_check_interval,
        )

    async def get_client(self, kind: RedisKind, force_reconnect: bool = False) -> Redis:
        """Возвращает (создаёт при необходимости) клиент для указанного kind.

        Args:
            kind: назначение подключения (cache/queue/limits).
            force_reconnect: принудительно пересоздать клиент.

        Returns:
            Экземпляр redis.asyncio.Redis.
        """
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
            await client.ping()
            self._clients[kind] = client

            self.logger.info(
                "Инициализирован Redis-клиент kind=%s db=%s",
                kind,
                self._db_for_kind(kind),
            )
            return client

    async def reset_client(self, kind: RedisKind) -> None:
        """Закрывает и сбрасывает клиент указанного kind."""
        async with self._locks[kind]:
            client = self._clients[kind]
            self._clients[kind] = None
            await self._safe_close(client)

    async def close(self) -> None:
        """Закрывает все клиенты (cache/queue/limits)."""
        for kind in ("cache", "queue", "limits"):
            await self.reset_client(kind)

    async def ensure_connected(self) -> None:
        """Инициализирует подключения для всех трёх kind'ов."""
        await self.get_client("cache")
        await self.get_client("queue")
        await self.get_client("limits")

    async def check_connection(self, kind: RedisKind) -> bool:
        """Проверяет доступность Redis для указанного kind.

        Args:
            kind: назначение подключения.

        Returns:
            True если ping успешен, иначе False.
        """
        try:
            client = await self.get_client(kind)
            return bool(await client.ping())
        except RedisError:
            return False
