"""Pub/Sub-канал invalidation для 3-tier RAG cache."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import orjson

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

__all__ = ("RagInvalidationBus",)

InvalidateHandler = Callable[[dict[str, Any]], Awaitable[None]]


class RagInvalidationBus:
    """Тонкий wrapper над Redis pub/sub для invalidate_by_tag-событий."""

    def __init__(
        self, channel: str = "rag:invalidation", redis_client: Any | None = None
    ) -> None:
        self._channel = channel
        self._client = redis_client
        self._task: asyncio.Task[None] | None = None
        self._handlers: list[InvalidateHandler] = []

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        from src.backend.infrastructure.clients.storage.redis import get_redis_client

        self._client = get_redis_client()
        return self._client

    async def publish(self, *, tag: str, **extra: Any) -> int:
        """Публикует invalidate-событие. Возвращает кол-во получателей."""
        client = self._ensure_client()
        payload = orjson.dumps({"tag": tag, **extra})
        try:
            return int(
                await client.execute(
                    "queue", lambda conn: conn.publish(self._channel, payload)
                )
            )
        except Exception as exc:
            logger.debug("RagInvalidationBus.publish failed: %s", exc)
            return 0

    def subscribe(self, handler: InvalidateHandler) -> None:
        """Регистрирует async-обработчик invalidate-сообщений."""
        self._handlers.append(handler)

    async def start(self) -> None:
        """Запускает фоновый listener (нужен ``task_registry`` для cancel)."""
        if self._task is not None and not self._task.done():
            return

        async def _listen() -> None:
            client = self._ensure_client()
            try:
                conn = await client.get_client("queue")
                pubsub = conn.pubsub()
                await pubsub.subscribe(self._channel)
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    raw = message.get("data")
                    try:
                        data = orjson.loads(raw)
                    except Exception as exc:
                        logger.debug("Invalid invalidate payload, skipped: %s", exc)
                        continue
                    for handler in list(self._handlers):
                        try:
                            await handler(data)
                        except Exception as exc:
                            logger.debug("Invalidation handler failed: %s", exc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("RagInvalidationBus listener stopped: %s", exc)

        from src.backend.core.utils.task_registry import get_task_registry

        self._task = get_task_registry().create_task(
            _listen(), name="rag-invalidation-listen"
        )

    async def stop(self) -> None:
        """Останавливает listener."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Listener stop с ошибкой: %s", exc)
        self._task = None
