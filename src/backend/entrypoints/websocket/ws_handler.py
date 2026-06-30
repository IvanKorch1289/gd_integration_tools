"""WebSocket-обработчик с унифицированной диспетчеризацией (Wave 1.5).

Каждое входящее WS-сообщение парсится как JSON и диспетчеризуется
через :func:`dispatch_action_or_dsl`: сначала пробуется
:class:`ActionGatewayDispatcher` (Tier 1/2 — если флаг
``USE_ACTION_DISPATCHER_FOR_WS`` включён и action зарегистрирован),
затем fallback на DSL-маршрут (Tier 3).

S163 W13: добавлены max_connections check и per-message timeout
через :class:`WSSettings`. Раньше WS не имел settings вообще.

S163 W33: option (A) bind at handshake — extract ``action_id`` из
``?action_id=xxx`` query param при connect, enforce per-route
``pool_size`` через :func:`get_dsl_service().get_route_overrides``.

S172 M1.1 (security GAP fix, ARC-001): явная auth-проверка на handshake.
Без валидного credential соединение отклоняется с WS close code 1008.
Auth facade (:func:`ws_auth.extract_credential`) поддерживает три источника:

* Sec-WebSocket-Protocol subprotocol (приоритет 1);
* ``auth_session`` cookie (приоритет 2, если ``ws_settings.allow_cookies``);
* ``?token=...`` query (приоритет 3, если ``ws_settings.allow_query_token``).

Поддерживаются API-key и JWT (см. :class:`WSAuthenticator`).
"""

import asyncio
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.backend.core.config.services.websocket import ws_settings
from src.backend.core.logging import get_logger
from src.backend.dsl.service import get_dsl_service
from src.backend.entrypoints._action_bridge import dispatch_action_or_dsl
from src.backend.entrypoints.websocket.ws_auth import (
    WSAuthError,
    extract_credential,
    get_ws_authenticator,
)
from src.backend.entrypoints.websocket.ws_manager import DEFAULT_ACTION_ID, ws_manager

__all__ = ("ws_router",)

logger = get_logger(__name__)


async def _ws_heartbeat_loop(
    websocket: WebSocket, *, client_id: str, interval_s: float
) -> None:
    """S163 W16: периодический ping для keepalive WS connection.

    Отправляет ``{"action": "ping"}`` каждые ``interval_s`` секунд.
    Клиент должен ответить ``{"action": "pong"}`` — main loop
    обрабатывает pong как обычное сообщение (no-op на стороне сервера).

    Heartbeat-task отменяется при закрытии connection (через
    ``asyncio.CancelledError`` в finally).
    """
    try:
        while True:
            await asyncio.sleep(interval_s)
            try:
                await websocket.send_json({"action": "ping"})
            except Exception as exc:  # connection closed
                logger.debug(
                    "WS heartbeat stopped client_id=%s reason=%s", client_id, exc
                )
                return
    except asyncio.CancelledError:
        return  # normal cleanup on connection close


def _resolve_pool_limit(action_id: str | None) -> int | None:
    """S163 W33: resolve effective pool limit для action_id.

    Returns:
        ``pool_size`` override из ``DslService.get_route_overrides()``
        если задан, иначе ``None`` (нет лимита на per-action уровне —
        только global ``ws_settings.max_connections``).
    """
    if not action_id or action_id == DEFAULT_ACTION_ID:
        return None
    try:
        overrides = get_dsl_service().get_route_overrides(action_id)
    except Exception as exc:
        logger.debug("get_route_overrides failed for action_id=%s: %s", action_id, exc)
        return None
    pool_size = overrides.get("pool_size")
    if isinstance(pool_size, int) and pool_size > 0:
        return pool_size
    return None


async def _authenticate_handshake(websocket: WebSocket) -> bool:
    """Auth на WS handshake (S172 M1.1).

    Закрывает connection с code 1008 при невалидном/missing credential.

    Returns:
        ``True`` если аутентификация успешна, ``False`` если закрыт.
    """
    # Accept уже вызван снаружи? Не вызываем здесь — caller решает accept/reject.
    try:
        subprotocol = websocket.headers.get("sec-websocket-protocol")
    except Exception:
        subprotocol = None
    try:
        cookies = dict(websocket.cookies) if websocket.cookies else {}
    except Exception:
        cookies = None
    try:
        query_token = websocket.query_params.get("token")
    except Exception:
        query_token = None

    credential = extract_credential(
        subprotocol=subprotocol,
        cookies=cookies,
        query_token=query_token,
        allow_query=getattr(ws_settings, "allow_query_token", False),
        allow_cookies=getattr(ws_settings, "allow_cookies", True),
    )

    if credential is None:
        await websocket.close(code=1008, reason="auth_required")
        logger.warning(
            "WS rejected: no credential (subprotocol=%s cookies=%s)",
            "yes" if subprotocol else "no",
            "yes" if cookies else "no",
        )
        return False

    authenticator = get_ws_authenticator()
    try:
        session = await authenticator.authenticate_via_facade(credential)
    except WSAuthError as exc:
        await websocket.close(code=1008, reason=f"auth_failed: {exc}")
        logger.warning(
            "WS rejected: auth failure source=%s method=%s reason=%s",
            credential.source,
            credential.method,
            exc,
        )
        return False
    except Exception as exc:
        await websocket.close(code=1011, reason="auth_error")
        logger.exception("WS rejected: auth error: %s", exc)
        return False

    # Stash session into state for downstream consumers.
    websocket.state.ws_session = session
    logger.debug(
        "WS authenticated principal=%s source=%s admin=%s",
        session.principal or session.client_id,
        session.auth_source,
        session.is_admin,
    )
    return True


ws_router = APIRouter(tags=["WebSocket"])


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Основной WebSocket endpoint.

    S163 W13: max_connections check через ws_settings.max_connections.
    Reject нового клиента с code 1008 если pool переполнен.

    S163 W33: per-action pool enforcement через ``?action_id=xxx`` query
    param. Если action_id передан, проверяется route_overrides["pool_size"]
    и текущий count в ws_manager. Reject с code 1008 если переполнен.

    S172 M1.1: обязательная auth на handshake (если ``require_auth=True``
    в :class:`WSSettings`). Закрытие с code 1008 при отсутствии/невалидности
    credential.

    Протокол сообщений (JSON):
        Запрос: ``{"action": "route_id", "payload": {...}}``
        Ответ: ``{"action": "route_id", "result": ..., "error": null}``
        Подписка: ``{"action": "subscribe", "groups": ["topic1"]}``

    Client contract (W33):
        Connect with ``?action_id=<route_id>`` для bind к route pool.
        Без action_id — попадает в DEFAULT pool (limited by
        ``ws_settings.max_connections`` только).
    """
    # S172 M1.1: опциональная auth на handshake. Можно отключить
    # ``WSSettings.require_auth=False`` для dev/test режима.
    require_auth = getattr(ws_settings, "require_auth", True)
    if require_auth:
        try:
            await websocket.accept()
        except Exception as exc:
            logger.debug("WS accept failed pre-auth: %s", exc)
            return
        if not await _authenticate_handshake(websocket):
            return
    else:
        await websocket.accept()

    # S163 W33: extract action_id из query params (option A bind at handshake).
    action_id_param = websocket.query_params.get("action_id") or None

    # S163 W13: pool-overflow protection (global, R-V15-14 connection pool).
    if ws_manager.active_count >= ws_settings.max_connections:
        await websocket.close(code=1008, reason="WS pool full")
        logger.warning(
            "WS rejected: max_connections=%d reached (action_id=%s)",
            ws_settings.max_connections,
            action_id_param or "<default>",
        )
        return

    # S163 W33: per-action pool enforcement.
    bound_action: str = action_id_param if action_id_param else DEFAULT_ACTION_ID
    pool_limit = _resolve_pool_limit(action_id_param)
    if pool_limit is not None:
        current = ws_manager.action_count(bound_action)
        if current >= pool_limit:
            await websocket.close(
                code=1008, reason=f"route pool full ({pool_limit} concurrent)"
            )
            logger.warning(
                "WS rejected: route pool full action_id=%s limit=%d",
                bound_action,
                pool_limit,
            )
            return

    client_id = uuid4().hex
    await ws_manager.connect(websocket, client_id, action_id=action_id_param)

    # S163 W16: heartbeat task (background ping per connection).
    # Отправляет {"action": "ping"} каждые heartbeat_interval_s секунд.
    # Клиент должен ответить {"action": "pong"} в течение message_timeout_s.
    heartbeat_task: asyncio.Task[None] | None = None
    if ws_settings.heartbeat_interval_s > 0:
        heartbeat_task = asyncio.create_task(
            _ws_heartbeat_loop(
                websocket=websocket,
                client_id=client_id,
                interval_s=ws_settings.heartbeat_interval_s,
            )
        )

    try:
        while True:
            # S163 W13: per-message timeout (защита от slow clients).

            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(), timeout=ws_settings.message_timeout_s
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
        ws_manager.disconnect(client_id, action_id=bound_action)
    except Exception as exc:
        logger.exception("WS ошибка: %s", exc)
        ws_manager.disconnect(client_id, action_id=bound_action)
    finally:
        # S163 W16: cancel heartbeat task при закрытии connection.
        if heartbeat_task is not None and not heartbeat_task.done():
            heartbeat_task.cancel()
