"""R1.fin (V11) — admin-эндпоинты ``/api/v1/{plugins,routes}/inventory``.

Возвращают JSON-каталог загруженных V11-плагинов и маршрутов из
``app.state``. Если соответствующий V11-loader выключен через
feature-flag (``V11_PLUGIN_LOADER_ENABLED`` /
``V11_ROUTE_LOADER_ENABLED``), эндпоинт отдаёт пустой массив + явный
флаг ``enabled=false`` в meta.

См. ADR-042/043/044.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

__all__ = ("plugins_router", "routes_router")


plugins_router: APIRouter = APIRouter()
"""Router для ``/plugins/*`` (mount-point настраивается в routers.py)."""

routes_router: APIRouter = APIRouter()
"""Router для ``/routes/*`` (mount-point настраивается в routers.py)."""


@plugins_router.get("/inventory", summary="Inventory загруженных V11-плагинов")
async def plugins_inventory(request: Request) -> dict[str, Any]:
    """Возвращает status всех V11-плагинов и meta loader'а.

    Status плагина — один из ``loaded`` / ``failed`` / ``skipped``;
    при ``failed`` поле ``reason`` содержит классифицированную причину
    (``manifest_error`` / ``capability_error`` / ``inventory_conflict``
    / ``import_error`` / ``lifecycle_error``).
    """
    loader = getattr(request.app.state, "plugin_loader_v11", None)
    if loader is None:
        return {
            "enabled": False,
            "reason": "V11_PLUGIN_LOADER_ENABLED=false",
            "plugins": [],
        }
    return {"enabled": True, "plugins": [entry.to_dict() for entry in loader.loaded]}


@routes_router.get("/inventory", summary="Inventory V11-маршрутов")
async def routes_inventory(request: Request) -> dict[str, Any]:
    """Возвращает status всех V11-маршрутов и meta loader'а.

    Status маршрута — один из ``enabled`` / ``disabled`` / ``failed``
    / ``skipped``. ``disabled`` означает, что ``feature_flag``
    зарезолвлен в False (route не активирован, capabilities не выделены).
    """
    loader = getattr(request.app.state, "route_loader_v11", None)
    if loader is None:
        return {
            "enabled": False,
            "reason": "V11_ROUTE_LOADER_ENABLED=false",
            "routes": [],
        }
    return {"enabled": True, "routes": [entry.to_dict() for entry in loader.loaded]}
