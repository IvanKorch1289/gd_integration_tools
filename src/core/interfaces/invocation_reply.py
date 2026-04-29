"""Контракт ``InvocationReplyChannel`` (W22.3).

Канал доставки ответа :class:`InvocationResponse` в асинхронных режимах
:class:`InvocationMode` (``ASYNC_API``, ``ASYNC_QUEUE``, ``BACKGROUND``,
``DEFERRED``, ``STREAMING``). Каждая реализация — конкретный backend:

* ``API`` — in-memory polling-store (клиент дёргает GET /invocations/{id}).
* ``QUEUE`` — публикация результата в брокер (Kafka/Rabbit/Redis Streams).
* ``WS`` — push в активный WebSocket-сокет по invocation_id.
* ``EMAIL`` — рассылка письма с результатом.
* ``EXPRESS`` — отправка в Express Bot диалог.

Контракт минимален: ``send`` (записать результат) и ``fetch``
(прочитать по ``invocation_id``). ``fetch`` для push-only каналов
(WS/EMAIL/EXPRESS) возвращает ``None`` — ответ не сохраняется,
только пробрасывается в момент send.

Не путать с :class:`src.infrastructure.clients.messaging.reply_channel.ReplyChannel`
(Wave 3.3) — там реализован Camel Request/Reply поверх event bus
с correlation_id; здесь — outbound channel для результата Invoker.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable

from src.core.interfaces.invoker import InvocationResponse

__all__ = ("ReplyChannelKind", "InvocationReplyChannel")


class ReplyChannelKind(str, Enum):
    """Тип канала доставки :class:`InvocationResponse`."""

    API = "api"
    QUEUE = "queue"
    WS = "ws"
    EMAIL = "email"
    EXPRESS = "express"


@runtime_checkable
class InvocationReplyChannel(Protocol):
    """Outbound channel для async-результатов Invoker.

    Контракт намеренно минимален. Push-only бэкенды (WS/EMAIL/EXPRESS)
    реализуют ``fetch`` как ``async def fetch(...) -> None`` —
    результат недоступен post-factum.
    """

    @property
    def kind(self) -> ReplyChannelKind:
        """Тип канала; используется для регистрации в registry."""
        ...

    async def send(self, response: InvocationResponse) -> None:
        """Доставить ответ через канал.

        Идемпотентно (повторный ``send`` для того же ``invocation_id``
        перезаписывает старый ответ для polling-каналов; push-каналы
        могут отправить повторно либо проигнорировать).
        """
        ...

    async def fetch(self, invocation_id: str) -> InvocationResponse | None:
        """Получить ранее доставленный ответ.

        Для push-only каналов (WS/EMAIL/EXPRESS) всегда возвращает
        ``None`` — у них нет сохранённого state.
        """
        ...
