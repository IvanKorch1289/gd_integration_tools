"""Request/Reply-channel поверх EventBus (Wave 3.3).

Реализует паттерн Request-Reply для асинхронных ответов через pub/sub:

1. Отправитель создаёт временный reply-subscription с уникальным
   ``reply_to`` channel и ``correlation_id`` (UUID).
2. Публикует запрос в целевой канал с метаданными ``reply_to`` и
   ``correlation_id``.
3. Ждёт ответ (``asyncio.Future``) с таймаутом. Listener в
   ``reply_to``-канале дёргает future по совпадению ``correlation_id``.
4. Subscription удаляется после получения ответа или истечения таймаута.

Используется для: AI-агентов, межсервисных запросов, долгих операций
без собственного ack-канала.

В отличие от request-response в HTTP — отправитель и получатель живут
в одном processе (либо в кластере, разделяющем Redis). EventBus
выступает транспортом; на FastStream/Redis он уже мультиплексирует
каналы без явной привязки consumer-группы.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.infrastructure.clients.messaging.event_bus import EventBus

__all__ = ("ReplyChannel", "ReplyTimeoutError", "DEFAULT_REPLY_TIMEOUT_S")

logger = logging.getLogger("eventing.reply_channel")

#: Таймаут по умолчанию для ``await_reply`` — 30 секунд.
DEFAULT_REPLY_TIMEOUT_S: float = 30.0

#: Префикс reply-каналов. EventBus consumer ловит всё, что начинается
#: с этого префикса, и разделяет по correlation_id.
REPLY_CHANNEL_PREFIX: str = "events.replies."


class ReplyTimeoutError(asyncio.TimeoutError):
    """Бросается, когда reply не пришёл за отведённое время."""


class ReplyChannel:
    """Singleton-диспетчер reply-future по correlation_id.

    Usage:

        channel = ReplyChannel.instance(event_bus=bus)
        reply = await channel.request(
            target_channel="events.ai.queries",
            payload={"q": "hello"},
            timeout=30.0,
        )

    Broker subscription на префикс ``REPLY_CHANNEL_PREFIX`` поднимается
    лениво при первом вызове ``request``. Subscription живёт пока жив
    broker и не перезапускается на каждый запрос — это дешевле.

    Идемпотентность: два ``request``-а с одинаковым ``correlation_id``
    не поддерживаются (должен быть уникальным).
    """

    _instance: "ReplyChannel | None" = None

    def __init__(self, event_bus: "EventBus") -> None:
        self._bus = event_bus
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._subscribed = False

    @classmethod
    def instance(cls, event_bus: "EventBus | None" = None) -> "ReplyChannel":
        """Возвращает singleton. На первый вызов обязателен ``event_bus``."""
        if cls._instance is None:
            if event_bus is None:
                from src.backend.infrastructure.clients.messaging.event_bus import (
                    get_event_bus,
                )

                event_bus = get_event_bus()
            cls._instance = cls(event_bus)
        return cls._instance

    async def request(
        self,
        *,
        target_channel: str,
        payload: dict[str, Any],
        timeout: float = DEFAULT_REPLY_TIMEOUT_S,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Публикует запрос и ждёт reply в пределах ``timeout`` секунд.

        Args:
            target_channel: Имя канала, куда уходит запрос.
            payload: Тело запроса (будет добавлено reply_to/correlation_id).
            timeout: Секунд ждать reply. По умолчанию 30.
            correlation_id: Внешний ID (обычно из Exchange). ``None`` —
                генерируется uuid4.

        Returns:
            Reply-payload (dict), опубликованный получателем в
            ``reply_to``-канал.

        Raises:
            ReplyTimeoutError: Если reply не пришёл за ``timeout``.
        """
        cid = correlation_id or str(uuid.uuid4())
        reply_channel = f"{REPLY_CHANNEL_PREFIX}{cid}"

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        async with self._lock:
            if cid in self._pending:
                raise ValueError(f"correlation_id {cid!r} уже имеет pending-request")
            self._pending[cid] = fut
            await self._ensure_subscribed()

        request = {"correlation_id": cid, "reply_to": reply_channel, "payload": payload}
        try:
            await self._bus_publish_raw(target_channel, request)
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise ReplyTimeoutError(
                f"reply timeout after {timeout}s (correlation_id={cid})"
            ) from exc
        finally:
            async with self._lock:
                self._pending.pop(cid, None)

    async def deliver(self, reply: dict[str, Any]) -> bool:
        """Handler для reply-сообщений. Дёргает соответствующий future.

        Returns:
            ``True`` — reply доставлен; ``False`` — нет pending-request
            с таким ``correlation_id`` (stale reply, игнорируется).
        """
        cid = reply.get("correlation_id")
        if not cid:
            logger.debug("reply без correlation_id, skip")
            return False
        async with self._lock:
            fut = self._pending.get(cid)
        if fut is None or fut.done():
            logger.debug("stale reply cid=%s", cid)
            return False
        fut.set_result(reply.get("payload", {}))
        return True

    async def _ensure_subscribed(self) -> None:
        if self._subscribed:
            return
        broker = getattr(self._bus, "_broker", None)
        if broker is None:
            logger.warning(
                "EventBus broker is None — ReplyChannel будет работать "
                "в in-process режиме до start()"
            )
            self._subscribed = True
            return
        try:
            subscriber = broker.subscriber(REPLY_CHANNEL_PREFIX + "*")  # type: ignore[attr-defined]
            subscriber(self.deliver)
            self._subscribed = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ReplyChannel subscribe failed (fallback in-process): %s", exc
            )
            self._subscribed = True

    async def _bus_publish_raw(self, channel: str, message: dict[str, Any]) -> None:
        """Публикация dict-а в канал в обход EventBus.publish (который
        требует pydantic BaseModel). Для request/reply у нас сырые dict-ы.
        """
        broker = getattr(self._bus, "_broker", None)
        if broker is None:
            logger.warning(
                "EventBus broker is None — публикация пропущена (channel=%s)", channel
            )
            return
        await broker.publish(message, channel=channel)
