"""Cross-instance WebSocket broadcast через Redis Pub/Sub.

Проблема: при N инстансах ws_manager держит connections локально,
broadcast не доходит до клиентов других инстансов.

Решение: публикуем сообщение в Redis, каждый инстанс subscribes
и пересылает подключенным у него клиентам.

Group membership: Redis SET (shared между инстансами), cache per-instance.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.infrastructure.clients.storage.redis_coordinator import RedisPubSub, RedisSet

__all__ = ("WSBroadcast", "ws_broadcast")

logger = logging.getLogger("entrypoints.websocket.broadcast")

_BROADCAST_CHANNEL = "ws:broadcast"


class WSBroadcast:
    """Координатор WS broadcast между инстансами.

    Each instance:
    - Subscribes to Redis channel "ws:broadcast"
    - On receive: forwards message to ALL LOCAL connected clients
    - Group membership: Redis SET "ws:group:{name}"
    """

    def __init__(self) -> None:
        self._pubsub = RedisPubSub(_BROADCAST_CHANNEL)
        self._listener_task: asyncio.Task | None = None
        self._local_handler: Any = None

    def set_local_handler(self, handler: Any) -> None:
        """Regisres function(msg: dict) for delivering to local connections.

        handler signature: async def handler(msg: dict) -> None
        """
        self._local_handler = handler

    async def start_listener(self) -> None:
        """Запускает фоновый subscriber на Redis channel."""
        if self._listener_task is not None:
            return

        async def _loop() -> None:
            try:
                async for msg in self._pubsub.subscribe():
                    if self._local_handler is not None and isinstance(msg, dict):
                        try:
                            await self._local_handler(msg)
                        except Exception as exc:
                            logger.warning("WS broadcast handler error: %s", exc)
            except asyncio.CancelledError:
                logger.info("WS broadcast listener cancelled")
            except Exception as exc:
                logger.error("WS broadcast listener crashed: %s", exc)

        self._listener_task = asyncio.create_task(_loop())
        logger.info("WS broadcast listener started")

    async def stop_listener(self) -> None:
        """Останавливает фоновый subscriber."""
        if self._listener_task is None:
            return
        self._listener_task.cancel()
        try:
            await self._listener_task
        except asyncio.CancelledError:
            pass
        self._listener_task = None

    async def publish(self, message: dict[str, Any]) -> int:
        """Публикует сообщение во все инстансы."""
        return await self._pubsub.publish(message)

    async def publish_to_group(self, group: str, message: dict[str, Any]) -> int:
        """Публикует сообщение в конкретную группу (через Redis SET membership)."""
        payload = {"group": group, "message": message}
        return await self._pubsub.publish(payload)

    def group(self, name: str) -> RedisSet:
        """Возвращает RedisSet для group membership."""
        return RedisSet(f"ws:group:{name}")


ws_broadcast = WSBroadcast()
