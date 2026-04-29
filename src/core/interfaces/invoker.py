"""Контракт Invoker (W22 — Single Invoker, главный Gateway).

Любая функция вызывается через ``Invoker.invoke`` с одним из шести
режимов. Любой протокол (HTTP/SOAP/gRPC/WS/MQ/Schedule) подключается
через адаптер, который собирает :class:`InvocationRequest` и передаёт
его в Invoker. Реальный обработчик выбирается через
:class:`ActionDispatcher`.

В этой версии (W22.1) контракт стабильный, реализован только режим
``sync``. Остальные режимы заглушены ``NotImplementedError`` —
прорастают в W22.2…W22.5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

__all__ = (
    "InvocationMode",
    "InvocationStatus",
    "InvocationRequest",
    "InvocationResponse",
    "Invoker",
)


class InvocationMode(str, Enum):
    """Шесть режимов вызова через Invoker.

    * ``SYNC`` — блокирующий вызов, ответ сразу.
    * ``ASYNC_API`` — fire-and-forget, ответ через API later (polling).
    * ``ASYNC_QUEUE`` — отправка в очередь TaskIQ/RabbitMQ, callback на
      ReplyChannel.
    * ``DEFERRED`` — отложенный запуск через scheduler.
    * ``BACKGROUND`` — фоновый запуск без отслеживания состояния.
    * ``STREAMING`` — потоковый вывод (Server-Sent Events / WebSocket).
    """

    SYNC = "sync"
    ASYNC_API = "async-api"
    ASYNC_QUEUE = "async-queue"
    DEFERRED = "deferred"
    BACKGROUND = "background"
    STREAMING = "streaming"


class InvocationStatus(str, Enum):
    """Статус вызова в response."""

    OK = "ok"
    ACCEPTED = "accepted"
    ERROR = "error"


@dataclass(slots=True)
class InvocationRequest:
    """Унифицированный запрос на выполнение action.

    Создаётся транспортным адаптером (HTTP-router, gRPC-handler, ...).
    """

    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    mode: InvocationMode = InvocationMode.SYNC
    reply_channel: str | None = None
    invocation_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InvocationResponse:
    """Унифицированный ответ Invoker.

    ``metadata`` копируется из :class:`InvocationRequest` для push-каналов
    (Email/Express/Queue), которым нужен routing-target (адрес/chat_id/topic).
    """

    invocation_id: str
    status: InvocationStatus
    result: Any = None
    error: str | None = None
    mode: InvocationMode = InvocationMode.SYNC
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Invoker(Protocol):
    """Главный Gateway: один вход для любого action и любого режима."""

    async def invoke(self, request: InvocationRequest) -> InvocationResponse:
        """Выполнить запрос согласно ``request.mode`` и вернуть ответ."""
        ...
