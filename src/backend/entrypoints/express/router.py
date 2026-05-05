"""Express HTTP-роутер: приём команд и callback от BotX.

Endpoints:
    POST /express/command   — входящая команда от пользователя.
    POST /express/callback  — результат async-операции от BotX.
    GET  /express/health    — healthcheck (BotX проверяет доступность бота).

Формат входящей команды (BotX → бот)::

    {
      "bot_id": "<UUID>",
      "sync_id": "<UUID>",                    // UUID этой команды
      "command": {"body": "/profile", "data": {...}, "metadata": {...}},
      "from": {"user_huid": "<UUID>", "username": "Alice", "ad_login": "alice"},
      "chat": {"group_chat_id": "<UUID>", "chat_type": "group_chat"},
      ...
    }

Каждая входящая команда передаётся в DSL-маршрут с route_id вида
``express.command.<command_name>`` (если зарегистрирован) или
``express.command.default`` (fallback).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

__all__ = ("router",)

_logger = logging.getLogger("entrypoints.express")

router = APIRouter(prefix="/express", tags=["express"])


async def _log_incoming(payload: dict[str, Any], *, sync_id: str) -> None:
    """Wave 9.2.4: запись входящего сообщения в ExpressDialogStore + ping сессии.

    Best-effort — Mongo-сбой не должен срывать обработку команды.
    """
    try:
        from src.core.di.providers import (
            get_express_dialog_store_provider,
            get_express_session_store_provider,
        )

        chat = payload.get("chat") or {}
        sender = payload.get("from") or {}
        bot_id = str(payload.get("bot_id", "")) or None
        group_chat_id = chat.get("group_chat_id") or ""
        user_huid = sender.get("user_huid")
        body = ""
        command = payload.get("command") or {}
        if isinstance(command, dict):
            body = str(command.get("body", "") or "")

        session_id = sync_id or group_chat_id or "unknown"

        await get_express_dialog_store_provider().append_message(
            session_id=session_id,
            role="user",
            body=body,
            bot_id=bot_id,
            group_chat_id=group_chat_id or None,
            user_huid=user_huid,
            sync_id=sync_id or None,
        )
        if session_id and session_id != "unknown":
            await get_express_session_store_provider().ping(session_id)
    except Exception as exc:  # noqa: BLE001
        _logger.debug("Express incoming log skipped: %s", exc)


@router.get("/health", summary="Express bot healthcheck")
async def health() -> dict[str, str]:
    """Healthcheck endpoint (BotX проверяет доступность бота).

    Returns:
        {"status": "ok"}
    """
    return {"status": "ok"}


@router.post("/command", summary="Приём команды от пользователя через BotX")
async def receive_command(request: Request) -> JSONResponse:
    """Принимает входящую команду от пользователя через BotX API.

    Маршрутизирует команду в зарегистрированный DSL-маршрут
    ``express.command.<name>``. Если маршрут не зарегистрирован — fallback на
    ``express.command.default``.

    Returns:
        Ответ для BotX (status=ok|error).
    """
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(
            {"status": "error", "reason": "invalid JSON"}, status_code=400
        )

    command = (payload.get("command") or {}).get("body", "")
    command_name = command.lstrip("/").split(maxsplit=1)[0] or "default"
    sync_id = payload.get("sync_id", "")
    chat = payload.get("chat") or {}
    sender = payload.get("from") or {}

    _logger.info(
        "Express command received: cmd=%r sync_id=%s user=%s chat=%s",
        command,
        sync_id,
        sender.get("user_huid"),
        chat.get("group_chat_id"),
    )

    try:
        from src.core.di.providers import get_express_metrics_recorder_provider

        recorder = get_express_metrics_recorder_provider()
        bot_name = str(payload.get("bot_id", "main_bot"))
        recorder(bot_name, command_name)
    except Exception:  # noqa: BLE001, S110
        pass

    # Wave 9.2.4: лог входящего сообщения в ExpressDialogStore.
    await _log_incoming(payload, sync_id=sync_id)

    route_id = f"express.command.{command_name}"
    fallback_id = "express.command.default"
    response = await _dispatch_to_route(route_id, fallback_id, payload, sync_id)
    return JSONResponse(response)


@router.post("/callback", summary="Callback от BotX по async-операции")
async def receive_callback(request: Request) -> JSONResponse:
    """Принимает результат асинхронной операции от BotX.

    BotX отправляет callback после доставки сообщения, обновления статуса,
    или завершения асинхронной операции. Результат маршрутизируется в
    ``express.callback`` если зарегистрирован.
    """
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(
            {"status": "error", "reason": "invalid JSON"}, status_code=400
        )

    sync_id = payload.get("sync_id", "")
    _logger.info("Express callback: sync_id=%s", sync_id)

    # Wave 9.2.4: ping сессии при получении callback'а.
    if sync_id:
        try:
            from src.core.di.providers import get_express_session_store_provider

            await get_express_session_store_provider().ping(sync_id)
        except Exception as exc:  # noqa: BLE001
            _logger.debug("Express callback session ping skipped: %s", exc)

    response = await _dispatch_to_route("express.callback", None, payload, sync_id)
    return JSONResponse(response)


async def _dispatch_to_route(
    route_id: str, fallback_id: str | None, payload: dict[str, Any], sync_id: str
) -> dict[str, Any]:
    """Маршрутизирует payload в action или DSL-pipeline (Wave 1.5).

    Сначала пробует :class:`ActionGatewayDispatcher` (если включён
    ``USE_ACTION_DISPATCHER_FOR_EXPRESS`` и action зарегистрирован),
    затем DSL-маршрут ``route_id``, затем DSL-маршрут ``fallback_id``.
    Контракт ответа BotX сохранён.

    Args:
        route_id: Основной идентификатор action/DSL-маршрута.
        fallback_id: Запасной DSL-маршрут (если основной не найден).
        payload: Тело входящего запроса BotX.
        sync_id: UUID входящего сообщения.

    Returns:
        Сериализуемый dict ответа для BotX.
    """
    from src.entrypoints._action_bridge import dispatch_action_or_dsl

    chat = payload.get("chat") or {}
    headers = {
        "X-Express-Sync-Id": sync_id,
        "X-Express-Chat-Id": chat.get("group_chat_id", ""),
        "X-Express-User-Huid": (payload.get("from") or {}).get("user_huid", ""),
    }

    bridge = await dispatch_action_or_dsl(
        action_id=route_id,
        dsl_route_id=route_id,
        payload=payload,
        transport="express",
        headers=headers,
        correlation_id=sync_id or None,
        attributes={"sync_id": sync_id} if sync_id else None,
    )
    if bridge.error_code == "action_not_found" and fallback_id:
        _logger.debug("Express dispatch: %s → fallback %s", route_id, fallback_id)
        bridge = await dispatch_action_or_dsl(
            action_id=fallback_id,
            dsl_route_id=fallback_id,
            payload=payload,
            transport="express",
            headers=headers,
            correlation_id=sync_id or None,
            attributes={"sync_id": sync_id} if sync_id else None,
        )

    if bridge.error_code == "action_not_found":
        _logger.warning("Express dispatch: маршрут %s не найден", route_id)
        return {"status": "ok", "reason": "no_route"}
    if not bridge.success:
        _logger.warning("Express dispatch ошибка: %s", bridge.error)
        return {"status": "error", "reason": bridge.error or "dispatch failed"}
    return {"status": "ok"}
