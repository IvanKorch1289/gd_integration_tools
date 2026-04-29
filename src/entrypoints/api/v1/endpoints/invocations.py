"""REST-адаптер для :class:`Invoker` (W22.2).

Единая точка входа для бизнес-команд через любой режим
:class:`InvocationMode`:

* ``POST /api/v1/invocations`` — выполнить request.
* ``GET /api/v1/invocations/{invocation_id}`` — polling результата
  (для режимов ``async-api`` и ``streaming`` через ``api`` reply-канал).

Streaming через WebSocket — в отдельном эндпоинте ``/ws/invocations``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from src.core.interfaces.invoker import (
    InvocationMode,
    InvocationRequest,
    InvocationStatus,
)
from src.schemas.invocation_api import InvocationRequestSchema, InvocationResponseSchema

__all__ = ("router",)

router = APIRouter(tags=["Invocations"])


@router.post(
    "",
    response_model=InvocationResponseSchema,
    summary="Выполнить action через Invoker",
)
async def post_invocation(
    request_body: InvocationRequestSchema,
    response: Response,
) -> InvocationResponseSchema:
    """Универсальный вход для всех режимов :class:`InvocationMode`.

    * ``sync`` — возвращает результат сразу (либо ошибку);
    * остальные режимы — возвращают 202 ACCEPTED + ``invocation_id``;
      результат опрашивается через GET ``/api/v1/invocations/{id}``
      (для ``api`` reply-канала) или приходит push'ом в WS/queue.
    """
    from src.services.execution.invoker import get_invoker

    invoker = get_invoker()
    invocation = await invoker.invoke(
        InvocationRequest(
            action=request_body.action,
            payload=request_body.payload,
            mode=InvocationMode(request_body.mode),
            reply_channel=request_body.reply_channel,
        )
    )
    if invocation.status is InvocationStatus.ACCEPTED:
        response.status_code = status.HTTP_202_ACCEPTED
    return InvocationResponseSchema(
        invocation_id=invocation.invocation_id,
        status=invocation.status.value,
        mode=invocation.mode.value,
        result=invocation.result,
        error=invocation.error,
    )


@router.get(
    "/{invocation_id}",
    response_model=InvocationResponseSchema,
    summary="Получить результат async/streaming-вызова (polling)",
)
async def get_invocation(invocation_id: str) -> InvocationResponseSchema:
    """Polling-результата через ``api`` reply-канал.

    Returns:
        404, если результат ещё не опубликован (или TTL истёк) либо
        invocation_id не существовал. Клиент должен ретраить.
    """
    from src.infrastructure.messaging.invocation_replies import (
        get_reply_channel_registry,
    )

    channel = get_reply_channel_registry().get("api")
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reply channel 'api' is not configured",
        )
    response = await channel.fetch(invocation_id)
    if response is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invocation '{invocation_id}' is not ready or unknown",
        )
    return InvocationResponseSchema(
        invocation_id=response.invocation_id,
        status=response.status.value,
        mode=response.mode.value,
        result=response.result,
        error=response.error,
    )
