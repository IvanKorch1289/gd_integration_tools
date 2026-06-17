"""WebSocket-обработчик с унифицированной диспетчеризацией (Wave 1.5).

Каждое входящее WS-сообщение парсится как JSON и диспетчеризуется
через :func:`dispatch_action_or_dsl`: сначала пробуется
:class:`ActionGatewayDispatcher` (Tier 1/2 — если флаг
``USE_ACTION_DISPATCHER_FOR_WS`` включён и action зарегистрирован),
затем fallback на DSL-маршрут (Tier 3).

S163 W13: добавлены max_connections check и per-message timeout
через :class:`WSSettings`. Раньше WS не имел settings вообще.
"""

from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.backend.core.config.services.websocket import ws_settings
from src.backend.core.logging import get_logger
from src.backend.entrypoints._action_bridge import dispatch_action_or_dsl
from src.backend.entrypoints.websocket.ws_manager import ws_manager

__all__ = ("ws_router",)

logger = get_logger(__name__)

ws_router = APIRouter(tags=["WebSocket"])


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Основной WebSocket endpoint.

    S163 W13: max_connections check через ws_settings.max_connections.
    Reject нового клиента с code 1008 если pool переполнен.

    Протокол сообщений (JSON):
        Запрос: ``{"action": "route_id", "payload": {...}}``
        Ответ: ``{"action": "route_id", "result": ..., "error": null}``
        Подписка: ``{"action": "subscribe", "groups": ["topic1"]}``
    """
    # S163 W13: pool-overflow protection (R-V15-14 connection pool).
    if ws_manager.active_count >= ws_settings.max_connections:
        await websocket.close(code=1008, reason="WS pool full")
        logger.warning(
            "WS rejected: max_connections=%d reached",
            ws_settings.max_connections,
        )
        return

    client_id = uuid4().hex
    await ws_manager.connect(websocket, client_id)

    try:
        while True:
            # S163 W13: per-message timeout (защита от slow clients).
            import asyncio

            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=ws_settings.message_timeout_s,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "WS message timeout client_id=%s timeout_s=%.1f",
                    client_id,
                    ws_settings.message_timeout_s,
                )
                await ws_manager.send_json(
                    client_id,
                    {"action": "error", "result": None, "error": "message_timeout"},
                )
                continue

            action = data.get("action", "")

            # Подписка на группы.
            if action == "subscribe":
                groups = data.get("groups", [])
                for group in groups:
                    ws_manager._groups.setdefault(group, set()).add(client_id)
                await ws_manager.send_json(
                    client_id,
                    {
                        "action": "subscribe",
                        "result": {"subscribed": groups},
                        "error": None,
                    },
                )
                continue

            # Унифицированная диспетчеризация Wave 1.5.
            try:
                bridge = await dispatch_action_or_dsl(
                    action_id=action,
                    dsl_route_id=action,
                    payload=data.get("payload", {}),
                    transport="ws",
                    headers={"ws-client-id": client_id, "ws-action": action},
                    attributes={"client_id": client_id},
                )
                if bridge.error_code == "action_not_found":
                    await ws_manager.send_json(
                        client_id,
                        {
                            "action": action,
                            "result": None,
                            "error": f"Маршрут '{action}' не найден",
                        },
                    )
                    continue
                await ws_manager.send_json(
                    client_id,
                    {"action": action, "result": bridge.data, "error": bridge.error},
                )
            except Exception as exc:
                logger.exception("WS ошибка обработки action=%s: %s", action, exc)
                await ws_manager.send_json(
                    client_id, {"action": action, "result": None, "error": str(exc)}
                )

    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)
    except Exception as exc:
        logger.exception("WS ошибка: %s", exc)
        ws_manager.disconnect(client_id)
