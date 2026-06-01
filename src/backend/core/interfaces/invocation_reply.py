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

from src.backend.core.interfaces.invoker import InvocationResponse

__all__ = ("ReplyChannelKind", "InvocationReplyChannel", "ReplyChannelRegistryProtocol")


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


@runtime_checkable
class ReplyChannelRegistryProtocol(Protocol):
    """Контракт реестра :class:`InvocationReplyChannel` для DI.

    Конкретная реализация живёт в
    :mod:`src.infrastructure.messaging.invocation_replies.registry`;
    services/ и entrypoints/ зависят только от этого Protocol через
    composition root (``app.state.reply_registry`` /
    :mod:`src.core.di.dependencies`).
    """

    def register(self, channel: InvocationReplyChannel) -> None:
        """Регистрирует backend; перезаписывает уже существующий той же kind."""
        ...

    def get(self, kind: ReplyChannelKind | str) -> InvocationReplyChannel | None:
        """Возвращает backend по типу; ``None`` — если не зарегистрирован."""
        ...

    def kinds(self) -> tuple[ReplyChannelKind, ...]:
        """Перечисляет зарегистрированные kinds (для introspection)."""
        ...
