"""REST-адаптер для :class:`Invoker` (W22.2).

Единая точка входа для бизнес-команд через любой режим
:class:`InvocationMode`:

* ``POST /api/v1/invocations`` — выполнить request.
* ``GET  /api/v1/invocations/{invocation_id}`` — polling результата
  (для режимов ``async-api`` и ``streaming`` через ``api`` reply-канал).

Streaming через WebSocket — в отдельном эндпоинте ``/ws/invocations``.

W26.5: маршруты регистрируются через ``router.add_api_route`` без
``@router``-декораторов. ``ActionSpec`` не используется, так как обоим
endpoint'ам нужен FastAPI ``Depends`` для DI Invoker/ReplyRegistry, что
не вписывается в ``service_getter``-контракт ActionRouterBuilder.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Response, status

from src.core.di.dependencies import get_invoker_dep, get_reply_registry
from src.core.interfaces.invoker import (
    InvocationMode,
    InvocationRequest,
    InvocationStatus,
)
from src.schemas.invocation_api import InvocationRequestSchema, InvocationResponseSchema

if TYPE_CHECKING:
    from src.core.interfaces.invocation_reply import ReplyChannelRegistryProtocol
    from src.core.interfaces.invoker import Invoker

__all__ = ("router",)

router = APIRouter(tags=["Invocations"])


async def post_invocation(
    request_body: InvocationRequestSchema,
    response: Response,
    invoker: "Invoker" = Depends(get_invoker_dep),
) -> InvocationResponseSchema:
    """Универсальный вход для всех режимов :class:`InvocationMode`.

    * ``sync`` — возвращает результат сразу (либо ошибку);
    * остальные режимы — возвращают 202 ACCEPTED + ``invocation_id``;
      результат опрашивается через GET ``/api/v1/invocations/{id}``
      (для ``api`` reply-канала) или приходит push'ом в WS/queue.
    """
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


async def get_invocation(
    invocation_id: str,
    registry: "ReplyChannelRegistryProtocol" = Depends(get_reply_registry),
) -> InvocationResponseSchema:
    """Polling-результата через ``api`` reply-канал.

    Returns:
        404, если результат ещё не опубликован (или TTL истёк) либо
        invocation_id не существовал. Клиент должен ретраить.
    """
    channel = registry.get("api")
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


router.add_api_route(
    path="",
    endpoint=post_invocation,
    methods=["POST"],
    response_model=InvocationResponseSchema,
    summary="Выполнить action через Invoker",
    name="post_invocation",
)
router.add_api_route(
    path="/{invocation_id}",
    endpoint=get_invocation,
    methods=["GET"],
    response_model=InvocationResponseSchema,
    summary="Получить результат async/streaming-вызова (polling)",
    name="get_invocation",
)
