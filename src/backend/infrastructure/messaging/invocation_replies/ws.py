"""WebSocket push-канал для :class:`InvocationResponse` (W22.3).

Push-only backend для режимов ``ASYNC_API``/``STREAMING``: клиент
устанавливает WS-соединение и регистрирует ``invocation_id``;
Invoker по завершении task'а вызывает ``send`` — сообщение
доставляется в открытый сокет.

``fetch`` всегда возвращает ``None`` — у канала нет сохранённого
состояния. Если клиент пропустил push (отвалилось соединение) —
повторно достать результат через WS невозможно; для надёжности
такой клиент должен дублировать polling через :class:`MemoryReplyChannel`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any, Protocol, runtime_checkable

from src.backend.core.interfaces.invocation_reply import (
    InvocationReplyChannel,
    ReplyChannelKind,
)
from src.backend.core.interfaces.invoker import InvocationResponse

__all__ = ("WsReplyChannel", "WsConnection")

logger = logging.getLogger("messaging.invocation_replies.ws")


@runtime_checkable
class WsConnection(Protocol):
    """Минимальный контракт WS-соединения, нужный каналу.

    Совместим с FastAPI/Starlette ``WebSocket`` (``send_json``).
    Изолирует backend от конкретного фреймворка.
    """

    async def send_json(self, data: dict[str, Any]) -> None: ...


class WsReplyChannel(InvocationReplyChannel):
    """Хранит активные WS-соединения и пушит ответы по invocation_id."""

    def __init__(self) -> None:
        self._connections: dict[str, WsConnection] = {}
        self._lock = asyncio.Lock()

    @property
    def kind(self) -> ReplyChannelKind:
        return ReplyChannelKind.WS

    async def register(self, invocation_id: str, connection: WsConnection) -> None:
        """Привязать invocation_id к открытому WS-соединению."""
        async with self._lock:
            self._connections[invocation_id] = connection

    async def unregister(self, invocation_id: str) -> None:
        """Удалить привязку (например, на закрытие WS)."""
        async with self._lock:
            self._connections.pop(invocation_id, None)

    async def send(self, response: InvocationResponse) -> None:
        async with self._lock:
            connection = self._connections.get(response.invocation_id)
        if connection is None:
            logger.debug(
                "WS push skipped: no connection for invocation_id=%s",
                response.invocation_id,
            )
            return
        try:
            await connection.send_json(_response_to_dict(response))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "WS push failed (invocation_id=%s): %s", response.invocation_id, exc
            )

    async def fetch(self, invocation_id: str) -> InvocationResponse | None:
        return None


def _response_to_dict(response: InvocationResponse) -> dict[str, Any]:
    """Сериализует :class:`InvocationResponse` в JSON-friendly dict."""
    raw = asdict(response)
    # Enum-значения превращаем в строки, чтобы json.dumps не упал.
    raw["status"] = response.status.value
    raw["mode"] = response.mode.value
    return raw
