"""WebSocket-обработчик с маршрутизацией через DSL.

Каждое входящее WS-сообщение парсится как JSON, определяется
route_id и диспетчеризуется через DslService. Результат
отправляется обратно клиенту.
"""

import logging
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dsl.service import get_dsl_service
from app.entrypoints.websocket.ws_manager import ws_manager

__all__ = ("ws_router",)

logger = logging.getLogger(__name__)

ws_router = APIRouter(tags=["WebSocket"])


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Основной WebSocket endpoint.

    Протокол сообщений (JSON):
        Запрос: ``{"action": "route_id", "payload": {...}}``
        Ответ: ``{"action": "route_id", "result": ..., "error": null}``
        Подписка: ``{"action": "subscribe", "groups": ["topic1"]}``
    """
    client_id = uuid4().hex
    await ws_manager.connect(websocket, client_id)

    try:
        while True:
            data = await websocket.receive_json()

            action = data.get("action", "")

            # Подписка на группы
            if action == "subscribe":
                groups = data.get("groups", [])
                for group in groups:
                    ws_manager._groups.setdefault(
                        group, set()
                    ).add(client_id)
                await ws_manager.send_json(
                    client_id,
                    {
                        "action": "subscribe",
                        "result": {"subscribed": groups},
                        "error": None,
                    },
                )
                continue

            # Маршрутизация через DSL
            try:
                dsl = get_dsl_service()
                exchange = await dsl.dispatch(
                    route_id=action,
                    body=data.get("payload", {}),
                    headers={
                        "ws-client-id": client_id,
                        "ws-action": action,
                    },
                )

                result = (
                    exchange.out_message.body
                    if exchange.out_message
                    else None
                )
                error = exchange.error

                await ws_manager.send_json(
                    client_id,
                    {
                        "action": action,
                        "result": result,
                        "error": error,
                    },
                )

            except KeyError:
                await ws_manager.send_json(
                    client_id,
                    {
                        "action": action,
                        "result": None,
                        "error": f"Маршрут '{action}' не найден",
                    },
                )
            except Exception as exc:
                logger.exception(
                    "WS ошибка обработки action=%s: %s",
                    action,
                    exc,
                )
                await ws_manager.send_json(
                    client_id,
                    {
                        "action": action,
                        "result": None,
                        "error": str(exc),
                    },
                )

    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)
    except Exception as exc:
        logger.exception("WS ошибка: %s", exc)
        ws_manager.disconnect(client_id)
