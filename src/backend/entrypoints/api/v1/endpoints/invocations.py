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

ADR-0421: ``POST /api/v1/invocations`` — универсальный диспетчер, поэтому
проверка прав обязательна: action с ``permissions``/``admin``-префиксом
требует соответствующего права, иначе 403 (fail-closed).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from src.backend.core.api.extensions import action_handler_registry
from src.backend.core.di.dependencies import get_invoker_dep, get_reply_registry
from src.backend.core.interfaces.invocation_reply import ReplyChannelRegistryProtocol
from src.backend.core.interfaces.invoker import (
    InvocationMode,
    InvocationRequest,
    InvocationStatus,
    Invoker,
)
from src.backend.dsl.commands.action_registry import (
    ActionPermissionDeniedError,
    enforce_action_permissions,
    resolve_action_permissions,
)
from src.backend.entrypoints.dependencies.rate_limit import get_default_rate_limiter
from src.backend.schemas.invocation_api import (
    InvocationRequestSchema,
    InvocationResponseSchema,
)

__all__ = ("router",)

router = APIRouter(tags=["Invocations"])


async def post_invocation(
    request_body: InvocationRequestSchema,
    response: Response,
    request: Request,
    invoker: Invoker = Depends(get_invoker_dep),
    _rate_limit: None = Depends(get_default_rate_limiter()),
) -> InvocationResponseSchema:
    """Универсальный вход для всех режимов :class:`InvocationMode`.

    * ``sync`` — возвращает результат сразу (либо ошибку);
    * остальные режимы — возвращают 202 ACCEPTED + ``invocation_id``;
      результат опрашивается через GET ``/api/v1/invocations/{id}``
      (для ``api`` reply-канала) или приходит push'ом в WS/queue.

    ADR-0421: универсальный диспетчер закрыт проверкой прав — action
    с ``permissions``/``admin``-префиксом требует соответствующего права,
    иначе 403 (fail-closed) без вызова Invoker'а.
    """
    auth = getattr(request.state, "auth", None)
    principal = getattr(auth, "principal", "") if auth is not None else ""
    permissions = resolve_action_permissions(auth)

    action = request_body.action
    required = action_handler_registry.required_permissions(action)
    if required:
        try:
            await enforce_action_permissions(
                action=action,
                required=required,
                granted=permissions,
                principal=principal,
            )
        except ActionPermissionDeniedError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=exc.to_detail()
            ) from exc

    invocation = await invoker.invoke(
        InvocationRequest(
            action=request_body.action,
            payload=request_body.payload,
            mode=InvocationMode(request_body.mode),
            reply_channel=request_body.reply_channel,
            principal=principal,
            permissions=permissions,
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
    registry: ReplyChannelRegistryProtocol = Depends(get_reply_registry),
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
    description=(
        "POST invocations execute the named action через configured Invoker "
        "и возвращают немедленный InvocationResponseSchema со status + "
        "result/error. Async actions возвращают invocation_id для polling "
        "через GET /invocations/{invocation_id}."
    ),
    tags=["Invocations"],
    responses={
        403: {"description": "Forbidden — action requires permissions (ADR-0421)."},
        422: {"description": "Validation error (invalid payload)."},
        429: {"description": "Rate limit exceeded (per default rate limiter)."},
        500: {"description": "Internal server error."},
    },
    name="post_invocation",
)
router.add_api_route(
    path="/{invocation_id}",
    endpoint=get_invocation,
    methods=["GET"],
    response_model=InvocationResponseSchema,
    summary="Получить результат async/streaming-вызова (polling)",
    description=(
        "GET invocation by ID для polling async/streaming results. "
        "Returns current status + result (if completed) или error. "
        "Status PENDING → retry with exponential backoff. "
        "Status COMPLETED → result populated, polling stops."
    ),
    tags=["Invocations"],
    responses={
        404: {"description": "Invocation not found или expired."},
        429: {"description": "Rate limit exceeded."},
    },
    name="get_invocation",
)
