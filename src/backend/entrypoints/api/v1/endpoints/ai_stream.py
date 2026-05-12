"""AI streaming endpoint (Wave D.3) — SSE token-level LLM stream.

``POST /api/v1/ai/llm/stream`` принимает chat-completion messages и стримит
ответы LLM в формате SSE. Auth: API_KEY или JWT (default-настройка).

События SSE:

* ``event: start`` — нулевой keep-alive с meta.
* ``event: token`` — каждый delta-токен.
* ``event: done`` — финальный chunk с usage и finish_reason.
* ``event: error`` — при ошибке стрима.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

import orjson
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from src.backend.entrypoints.api.dependencies.auth_selector import (
    AuthMethod,
    require_auth,
)

logger = logging.getLogger(__name__)

__all__ = ("router",)

router = APIRouter()


class StreamRequest(BaseModel):
    """Тело запроса /llm/stream."""

    messages: list[dict[str, Any]] = Field(..., min_length=1)
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=32_000)


def _sse_event(event: str, data: dict[str, Any]) -> bytes:
    payload = orjson.dumps(data).decode("utf-8")
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


async def _generate(
    request: Request, payload: StreamRequest
) -> AsyncIterator[bytes]:
    from src.backend.services.ai.streaming_service import (
        get_llm_streaming_service,
    )

    service = get_llm_streaming_service()
    yield _sse_event("start", {"model": payload.model})

    kwargs: dict[str, Any] = {}
    if payload.temperature is not None:
        kwargs["temperature"] = payload.temperature
    if payload.max_tokens is not None:
        kwargs["max_tokens"] = payload.max_tokens

    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    try:
        async for chunk in service.astream(
            payload.messages, model=payload.model, **kwargs
        ):
            if await request.is_disconnected():
                logger.info("ai/llm/stream: client disconnected — закрываем upstream")
                break
            if chunk.delta:
                yield _sse_event(
                    "token", {"delta": chunk.delta, "finish_reason": chunk.finish_reason}
                )
            if chunk.usage:
                usage = chunk.usage
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason
                break
        yield _sse_event(
            "done",
            {"finish_reason": finish_reason or "stop", "usage": usage or {}},
        )
    except asyncio.CancelledError:
        yield _sse_event("error", {"error": "cancelled"})
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("ai/llm/stream error: %s", exc)
        yield _sse_event("error", {"error": str(exc)})


@router.post(
    "/llm/stream",
    summary="SSE token-level стрим LLM (D.3)",
    dependencies=[Depends(require_auth([AuthMethod.API_KEY, AuthMethod.JWT]))],
)
async def llm_stream(request: Request, payload: StreamRequest) -> StreamingResponse:
    """Стримит токены LLM как Server-Sent Events.

    Capability ``ai.stream`` проверяется на уровне route-loader'а (если
    маршрут зарегистрирован декларативно). Endpoint всегда доступен при
    включённом ``LITELLM_ENABLED=true``.
    """
    from src.backend.core.config.ai_2026 import litellm_gateway_settings

    if not litellm_gateway_settings.enabled:
        raise HTTPException(
            status_code=503, detail="LiteLLMGateway disabled (LITELLM_ENABLED=false)."
        )
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        _generate(request, payload),
        media_type="text/event-stream",
        headers=headers,
    )
