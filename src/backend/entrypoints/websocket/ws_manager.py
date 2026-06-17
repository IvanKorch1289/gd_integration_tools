"""Менеджер WebSocket-подключений.

Управляет жизненным циклом WS-подключений, поддерживает
broadcast и отправку сообщений по группам.

S163 W25-A: добавлено per-action tracking (``_connections_by_action``)
для option (A) bind at handshake. Каждое WS-соединение может быть
привязано к конкретному action_id (через query param при connect),
что позволяет per-route pool enforcement через route_overrides.
"""

from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from src.backend.core.logging import get_logger

__all__ = ("ConnectionManager", "ws_manager")

logger = get_logger(__name__)

# S163 W25-A: sentinel для default pool (без action_id в query params).
# Backward-compat: если клиент НЕ передаёт action_id, попадает в общий
# pool с лимитом ws_settings.max_connections.
DEFAULT_ACTION_ID = "__default__"


class ConnectionManager:
    """Менеджер активных WebSocket-подключений.

    Поддерживает:
    - Подключение/отключение клиентов.
    - Подписку на группы (topic).
    - Broadcast всем или по группе.
    - Отправку сообщения конкретному клиенту.
    - S163 W25-A: per-action_id tracking для per-route pool enforcement.
    """

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._groups: dict[str, set[str]] = {}
        # S163 W25-A: action_id → set of client_ids (для per-route pool).
        self._connections_by_action: dict[str, set[str]] = {}

    @property
    def active_count(self) -> int:
        """Количество активных подключений."""
        return len(self._connections)

    def action_count(self, action_id: str) -> int:
        """S163 W25-A: количество активных подключений для action_id.

        Args:
            action_id: route_id или ``DEFAULT_ACTION_ID`` для default pool.

        Returns:
            Количество активных WS-соединений, привязанных к этому action.
        """
        return len(self._connections_by_action.get(action_id, set()))

    def actions_with_capacity(
        self, *, action_pool_size: int
    ) -> dict[str, int]:
        """S163 W25-A: для diagnostics — все actions и их текущий count.

        Args:
            action_pool_size: Используется только для вычисления available
                capacity (необязательный, для отчётов).

        Returns:
            Dict ``{action_id: current_count}``.
        """
        return {
            action_id: len(clients)
            for action_id, clients in self._connections_by_action.items()
        }

    async def connect(
        self,
        websocket: WebSocket,
        client_id: str,
        groups: list[str] | None = None,
        action_id: str | None = None,
    ) -> None:
        """Принимает WebSocket-подключение.

        Args:
            websocket: WebSocket-соединение.
            client_id: Уникальный идентификатор клиента.
            groups: Список групп для подписки.
            action_id: S163 W25-A — route_id, к которому привязано это
                соединение (из query params ``?action_id=xxx``). ``None``
                или отсутствие → :data:`DEFAULT_ACTION_ID` pool.
        """
        await websocket.accept()
        self._connections[client_id] = websocket

        bound_action = action_id if action_id else DEFAULT_ACTION_ID
        self._connections_by_action.setdefault(bound_action, set()).add(
            client_id
        )

        for group in groups or []:
            self._groups.setdefault(group, set()).add(client_id)

        logger.info(
            "WS подключён: client_id=%s, action_id=%s, groups=%s",
            client_id,
            bound_action,
            groups,
        )

    def disconnect(self, client_id: str, action_id: str | None = None) -> None:
        """Отключает клиента.

        Args:
            client_id: Идентификатор клиента.
            action_id: S163 W25-A — action_id, к которому был привязан
                клиент. ``None`` → попытка удалить из всех pools (safe
                fallback если caller не помнит action_id).
        """
        self._connections.pop(client_id, None)

        # S163 W25-A: cleanup per-action tracking.
        if action_id is not None:
            clients = self._connections_by_action.get(action_id)
            if clients is not None:
                clients.discard(client_id)
                if not clients:
                    self._connections_by_action.pop(action_id, None)
        else:
            # Safe fallback: удалить из всех pools.
            for clients in self._connections_by_action.values():
                clients.discard(client_id)
            # Compact empty pools.
            self._connections_by_action = {
                a: c
                for a, c in self._connections_by_action.items()
                if c
            }

        for group_members in self._groups.values():
            group_members.discard(client_id)

        logger.info("WS отключён: client_id=%s", client_id)

    async def send_json(self, client_id: str, data: dict[str, Any]) -> None:
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
            except Exception as _:
                disconnected.append(client_id)

        for client_id in disconnected:
            self.disconnect(client_id)


ws_manager = ConnectionManager()
