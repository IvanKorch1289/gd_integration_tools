"""Менеджер WebSocket-подключений.

Управляет жизненным циклом WS-подключений, поддерживает
broadcast и отправку сообщений по группам.
"""

import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

__all__ = ("ConnectionManager", "ws_manager")

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Менеджер активных WebSocket-подключений.

    Поддерживает:
    - Подключение/отключение клиентов.
    - Подписку на группы (topic).
    - Broadcast всем или по группе.
    - Отправку сообщения конкретному клиенту.
    """

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._groups: dict[str, set[str]] = {}

    @property
    def active_count(self) -> int:
        """Количество активных подключений."""
        return len(self._connections)

    async def connect(
        self,
        websocket: WebSocket,
        client_id: str,
        groups: list[str] | None = None,
    ) -> None:
        """Принимает WebSocket-подключение.

        Args:
            websocket: WebSocket-соединение.
            client_id: Уникальный идентификатор клиента.
            groups: Список групп для подписки.
        """
        await websocket.accept()
        self._connections[client_id] = websocket

        for group in groups or []:
            self._groups.setdefault(group, set()).add(client_id)

        logger.info(
            "WS подключён: client_id=%s, groups=%s",
            client_id,
            groups,
        )

    def disconnect(self, client_id: str) -> None:
        """Отключает клиента.

        Args:
            client_id: Идентификатор клиента.
        """
        self._connections.pop(client_id, None)

        for group_members in self._groups.values():
            group_members.discard(client_id)

        logger.info("WS отключён: client_id=%s", client_id)

    async def send_json(
        self, client_id: str, data: dict[str, Any]
    ) -> None:
        """Отправляет JSON конкретному клиенту.

        Args:
            client_id: Идентификатор клиента.
            data: Данные для отправки.
        """
        ws = self._connections.get(client_id)
        if ws and ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json(data)

    async def broadcast(
        self, data: dict[str, Any], *, group: str | None = None
    ) -> None:
        """Рассылает JSON всем или по группе.

        Args:
            data: Данные для рассылки.
            group: Имя группы (если ``None`` — всем).
        """
        if group is not None:
            target_ids = self._groups.get(group, set())
        else:
            target_ids = set(self._connections.keys())

        disconnected: list[str] = []

        for client_id in target_ids:
            ws = self._connections.get(client_id)
            if ws is None or ws.client_state != WebSocketState.CONNECTED:
                disconnected.append(client_id)
                continue
            try:
                await ws.send_json(data)
            except Exception:
                disconnected.append(client_id)

        for client_id in disconnected:
            self.disconnect(client_id)


ws_manager = ConnectionManager()
