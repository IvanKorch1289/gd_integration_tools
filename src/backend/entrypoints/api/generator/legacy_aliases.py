"""P0-2 (cycle 241): URL-алиасы для legacy frontend-контракта.

Streamlit-клиенты (44+ страниц) вызывают
``/api/v1/{resource}/{verb}/`` с REST-конвенцией (``all``, ``create``,
``update/<id>``, ``delete/<id>``). Реальный backend экспонирует
``/api/v1/auto/<resource>.<verb>`` через :mod:`auto_register`.

Этот модуль создаёт 16 статических alias-роутов, которые диспатчат
на ``ActionHandlerRegistry.dispatch()`` с правильным action-именем.

Ponytail: 16 thin handlers, прямой вызов registry, без in-process HTTP.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from src.backend.core.logging import get_logger
from src.backend.schemas.invocation import ActionCommandSchema

__all__ = ("register_legacy_aliases",)


logger = get_logger(__name__)


async def _dispatch_with(
    request: Request, action: str, item_id: int | None = None
) -> JSONResponse:
    """Диспатч запроса на конкретный action.

    Args:
        action: имя action в реестре (например, ``orders.list``).
        item_id: ID из path для update/delete (если есть).
    """
    try:
        body: dict[str, Any] = {}
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                body = await request.json()
            except Exception:
                body = {}
        payload = dict(request.query_params)
        payload.update(body)
        if item_id is not None:
            payload["id"] = item_id
    except Exception as exc:
        return JSONResponse(status_code=400, content={"detail": f"Bad request: {exc}"})

    try:
        from src.backend.dsl.commands.action_registry import action_handler_registry

        # action_handler_registry — singleton instance
        registry = action_handler_registry
        command = ActionCommandSchema(action=action, payload=payload, mode="sync")
        result = await registry.dispatch(command)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Action '{action}' не найден в реестре"},
        )
    except Exception as exc:
        logger.exception("legacy_alias_dispatch_failed action=%s", action)
        return JSONResponse(
            status_code=500, content={"detail": f"Action dispatch failed: {exc}"}
        )

    return JSONResponse(content={"result": result, "action": action})


# Статические маппинги: 4 resources × 4 verbs = 16 routes
_ALIASES: list[tuple[str, dict[str, str], list[str]]] = [
    # (path, handler_args, action_name, http_methods)
    # path : /api/v1/{resource}/{verb}[/{item_id}]
    ("/orders/all/", {"action": "orders.list"}, ["GET"]),
    ("/orders/create/", {"action": "orders.create"}, ["POST"]),
    (
        "/orders/update/{item_id}",
        {"action": "orders.update", "item_id": "path"},
        ["PUT"],
    ),
    (
        "/orders/delete/{item_id}",
        {"action": "orders.delete", "item_id": "path"},
        ["DELETE"],
    ),
    ("/users/all/", {"action": "users.list"}, ["GET"]),
    ("/users/create/", {"action": "users.create"}, ["POST"]),
    ("/users/update/{item_id}", {"action": "users.update", "item_id": "path"}, ["PUT"]),
    (
        "/users/delete/{item_id}",
        {"action": "users.delete", "item_id": "path"},
        ["DELETE"],
    ),
    ("/files/all/", {"action": "files.list"}, ["GET"]),
    ("/files/create/", {"action": "files.create"}, ["POST"]),
    ("/files/update/{item_id}", {"action": "files.update", "item_id": "path"}, ["PUT"]),
    (
        "/files/delete/{item_id}",
        {"action": "files.delete", "item_id": "path"},
        ["DELETE"],
    ),
    ("/orderkinds/all/", {"action": "orderkinds.list"}, ["GET"]),
    ("/orderkinds/create/", {"action": "orderkinds.create"}, ["POST"]),
    (
        "/orderkinds/update/{item_id}",
        {"action": "orderkinds.update", "item_id": "path"},
        ["PUT"],
    ),
    (
        "/orderkinds/delete/{item_id}",
        {"action": "orderkinds.delete", "item_id": "path"},
        ["DELETE"],
    ),
]


def _make_handler(action: str, with_item_id: bool):
    """Создать замыкание-handler для конкретного action."""
    if with_item_id:

        async def _handler(request: Request, item_id: int) -> JSONResponse:
            return await _dispatch_with(request, action=action, item_id=item_id)

        return _handler
    else:

        async def _handler(request: Request) -> JSONResponse:
            return await _dispatch_with(request, action=action, item_id=None)

        return _handler


def _build_alias_router() -> APIRouter:
    """Создаёт router с 16 legacy-URL алиасами."""
    router = APIRouter(prefix="/api/v1", include_in_schema=False)

    for path, params, methods in _ALIASES:
        action = params["action"]
        with_item_id = params.get("item_id") == "path"
        handler = _make_handler(action, with_item_id)
        router.add_api_route(path, handler, methods=methods, name=f"legacy.{action}")

    return router


def register_legacy_aliases(app: FastAPI) -> int:
    """Подключает legacy URL-алиасы к FastAPI app.

    Returns:
        Число зарегистрированных routes (16).
    """
    router = _build_alias_router()
    app.include_router(router)
    return 16
