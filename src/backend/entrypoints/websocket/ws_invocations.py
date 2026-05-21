"""WebSocket-адаптер для :class:`Invoker` (W22.2).

Позволяет клиенту запустить action в режимах ``streaming`` или
``async-api`` и получать push'и :class:`InvocationResponse` через
открытый WebSocket-сокет (без polling-а).

Протокол сообщений (JSON):

* Клиент → сервер::

      {
          "type": "invoke",
          "action": "users.list",
          "payload": {...},
          "mode": "streaming",     // или "async-api" / "background"
          "invocation_id": "..."   // опционально — иначе генерируется
      }

* Сервер → клиент (от :class:`WsReplyChannel`)::

      {
          "invocation_id": "...",
          "status": "ok"|"error"|"accepted",
          "mode": "...",
          "result": <chunk>,
          "error": null
      }

Сообщение ``{"type": "ack", "invocation_id": ...}`` возвращается
сразу после регистрации. Сокет закрывается со стороны клиента.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.backend.core.interfaces.invoker import InvocationMode, InvocationRequest

__all__ = ("ws_invocations_router",)

logger = logging.getLogger("entrypoints.websocket.invocations")

ws_invocations_router = APIRouter(tags=["WebSocket · Invocations"])


@ws_invocations_router.websocket("/ws/invocations")
async def websocket_invocations(websocket: WebSocket) -> None:
    """WS-эндпоинт для streaming/async-api вызовов через Invoker.

    DI: ``ReplyChannelRegistry`` и ``Invoker`` берутся из
    ``websocket.app.state`` (composition root в
    :func:`src.plugins.composition.di.register_app_state`).
    """
    await websocket.accept()
    registry = websocket.app.state.reply_registry
    invoker = websocket.app.state.invoker
    ws_channel = registry.get("ws")
    if ws_channel is None:
        await websocket.send_json(
            {"type": "error", "error": "WS reply channel is not configured"}
        )
        await websocket.close()
        return

    # Список invocation_id, привязанных к этому соединению — чтобы
    # корректно unregister'нуть всё на disconnect.
    bound: list[str] = []

    try:
        while True:
            data = await websocket.receive_json()
            if not isinstance(data, dict):
                await websocket.send_json(
                    {"type": "error", "error": "expected JSON object"}
                )
                continue

            msg_type = data.get("type")
            if msg_type != "invoke":
                await websocket.send_json(
                    {"type": "error", "error": f"unknown type '{msg_type}'"}
                )
                continue

            action = data.get("action")
            if not isinstance(action, str) or not action:
                await websocket.send_json(
                    {"type": "error", "error": "'action' must be non-empty string"}
                )
                continue

            mode = _coerce_mode(data.get("mode", "streaming"))
            if mode is None:
                await websocket.send_json(
                    {"type": "error", "error": f"invalid mode '{data.get('mode')}'"}
                )
                continue

            invocation_id = data.get("invocation_id") or uuid4().hex
            payload = (
                data.get("payload") if isinstance(data.get("payload"), dict) else {}
            )

            # Wave D.3: специальный канал ``llm.stream`` — обходим Invoker
            # и стримим токены напрямую через LLMStreamingService.
            if action == "llm.stream":
                await websocket.send_json(
                    {"type": "ack", "invocation_id": invocation_id}
                )
                await _stream_llm_to_ws(
                    websocket=websocket, invocation_id=invocation_id, payload=data
                )
                continue

            # Привязываем сокет к invocation_id ДО запуска вызова, иначе
            # ранние chunks от STREAMING-task'а потеряются.
            await ws_channel.register(invocation_id, websocket)
            bound.append(invocation_id)

            await websocket.send_json({"type": "ack", "invocation_id": invocation_id})

            # W22 F.2 A2: все режимы (включая SYNC) идут через Invoker.
            # Для SYNC ответ возвращается напрямую как InvocationResponse —
            # сразу пушим его в сокет; для остальных режимов Invoker сам
            # управляет каналами и task-life-cycle.
            request = InvocationRequest(
                action=action,
                payload=payload,
                mode=mode,
                reply_channel="ws",
                invocation_id=invocation_id,
                correlation_id=invocation_id,
            )
            response = await invoker.invoke(request)
            if mode is InvocationMode.SYNC:
                await websocket.send_json(_response_payload(response))

    except WebSocketDisconnect:
        logger.debug("WS /ws/invocations disconnected")
    except Exception as exc:  # noqa: BLE001
        logger.exception("WS /ws/invocations failed: %s", exc)
    finally:
        for invocation_id in bound:
            try:
                await ws_channel.unregister(invocation_id)
            except Exception:  # noqa: BLE001
                logger.debug("unregister failed for %s", invocation_id, exc_info=True)


def _coerce_mode(value: Any) -> InvocationMode | None:
    """Возвращает :class:`InvocationMode` или ``None`` при некорректном вводе."""
    if isinstance(value, InvocationMode):
        return value
    if isinstance(value, str):
        try:
            return InvocationMode(value)
        except ValueError:
            return None
    return None


def _response_payload(response: Any) -> dict[str, Any]:
    """Конвертирует :class:`InvocationResponse` в WS-friendly dict."""
    return {
        "invocation_id": response.invocation_id,
        "status": response.status.value,
        "mode": response.mode.value,
        "result": response.result,
        "error": response.error,
    }


async def _stream_llm_to_ws(
    *, websocket: WebSocket, invocation_id: str, payload: dict[str, Any]
) -> None:
    """Wave D.3: token-level LLM streaming через WS channel."""
    from src.backend.services.ai.streaming_service import get_llm_streaming_service

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        await websocket.send_json(
            {
                "type": "error",
                "invocation_id": invocation_id,
                "error": "'messages' must be non-empty list",
            }
        )
        return

    model = payload.get("model")
    kwargs: dict[str, Any] = {}
    if isinstance(payload.get("temperature"), (int, float)):
        kwargs["temperature"] = payload["temperature"]
    if isinstance(payload.get("max_tokens"), int):
        kwargs["max_tokens"] = payload["max_tokens"]

    service = get_llm_streaming_service()
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    try:
        async for chunk in service.astream(messages, model=model, **kwargs):
            if chunk.delta:
                await websocket.send_json(
                    {
                        "type": "token",
                        "invocation_id": invocation_id,
                        "delta": chunk.delta,
                    }
                )
            if chunk.usage:
                usage = chunk.usage
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason
                break
        await websocket.send_json(
            {
                "type": "done",
                "invocation_id": invocation_id,
                "finish_reason": finish_reason or "stop",
                "usage": usage or {},
            }
        )
    except WebSocketDisconnect:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm.stream over WS failed: %s", exc)
        await websocket.send_json(
            {"type": "error", "invocation_id": invocation_id, "error": str(exc)}
        )
