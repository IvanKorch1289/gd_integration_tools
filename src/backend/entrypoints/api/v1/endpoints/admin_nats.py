"""Admin endpoints для мониторинга NATS JetStream consumers (S13 K3 W5).

Endpoints:

* ``GET /api/v1/admin/nats/consumers`` — список зарегистрированных consumers
  с метриками lag'а;
* ``GET /api/v1/admin/nats/consumers/{stream}/{durable}/info`` — детальный
  ``consumer_info`` для конкретного consumer'а.

Защищён ``require_admin((AdminRole.OPERATOR, AdminRole.READ_ONLY))``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from src.backend.core.auth.admin_roles import AdminRole, require_admin

__all__ = ("router",)

router = APIRouter(prefix="/admin/nats", tags=["Admin / NATS"])


_REGISTRY: dict[str, Any] = {}


def register_nats_source(source: Any) -> None:
    """Регистрирует :class:`NATSJetStreamSource` для admin-инвентаря.

    Вызывается из ``plugins/composition`` после старта source'а.
    """
    key = getattr(source, "source_id", None)
    if key is None:
        return
    _REGISTRY[str(key)] = source


def unregister_nats_source(source_id: str) -> None:
    """Удаляет источник из реестра при shutdown."""
    _REGISTRY.pop(source_id, None)


@router.get(
    "/consumers",
    dependencies=[Depends(require_admin((AdminRole.OPERATOR, AdminRole.READ_ONLY)))],
    summary="Список NATS JetStream consumers",
    description=(
        "Возвращает список всех зарегистрированных NATS JetStream consumers "
        "с текущим lag-снапшотом (delivered/ack-pending/num-pending). "
        "Требует прав OPERATOR или READ_ONLY. Endpoint сканирует реестр "
        "_REGISTRY (populated by register_nats_source при startup)."
    ),
    responses={
        200: {"description": "Consumer list with lag snapshots."},
        401: {"description": "Unauthenticated."},
        403: {"description": "Forbidden — insufficient admin role."},
    },
)
async def list_consumers() -> dict[str, Any]:
    """Список всех зарегистрированных NATS consumers с lag-снапшотами."""
    # Lazy importlib для соблюдения layer policy (entrypoints не зависит
    # от infrastructure статически; metrics-emitter резолвится в runtime).
    import importlib

    metrics_mod = importlib.import_module(
        "src.backend.infrastructure.observability.nats_metrics"
    )

    items: list[dict[str, Any]] = []
    for source_id, source in _REGISTRY.items():
        try:
            info = await source.fetch_consumer_info()
        except Exception as exc:
            info = {"error": str(exc), "source_id": source_id}
        info["source_id"] = source_id
        metrics_mod.record_consumer_info(info)
        items.append(info)
    return {"consumers": items, "total": len(items)}


@router.get(
    "/consumers/{stream}/{durable}/info",
    dependencies=[Depends(require_admin((AdminRole.OPERATOR, AdminRole.READ_ONLY)))],
    summary="Детальный consumer_info для stream/durable",
    description=(
        "Возвращает детальный consumer_info для указанной пары "
        "stream/durable. Source_id формируется как `nats_js:{stream}:{durable}`. "
        "404 если consumer не зарегистрирован."
    ),
    responses={
        200: {"description": "Consumer info returned."},
        401: {"description": "Unauthenticated."},
        403: {"description": "Forbidden — insufficient admin role."},
        404: {"description": "NATS consumer not registered (unknown stream/durable)."},
    },
)
async def get_consumer_info(stream: str, durable: str) -> dict[str, Any]:
    """Детальный consumer_info для указанного stream/durable."""
    source_id = f"nats_js:{stream}:{durable}"
    source = _REGISTRY.get(source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NATS consumer not registered: {source_id}",
        )
    return await source.fetch_consumer_info()
