"""Runtime-метрики платформы: пулы соединений и процессы workflow (ADR-0439).

Endpoints (под ``/api/v1/admin``):

* ``GET /pools/snapshot`` — метрики пулов соединений (idle/active/total);
* ``GET /processes/active`` — инстансы workflow'а, готовые к обработке;
* ``GET /processes/stats`` — количество инстансов по статусам.

Сводка очередей (Kafka/RabbitMQ) в этом наборе **нет**: общей capability
«метрики брокера» в кодовой базе не существует (есть только NATS-специфичный
``GET /api/v1/admin/nats/consumers``) — панель портала остаётся выключенной
(owner-задача §16).

Авторизация: admin-роль (``OPERATOR`` / ``SUPER_ADMIN``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from src.backend.core.auth.admin_roles import AdminRole, require_admin
from src.backend.core.logging import get_logger

__all__ = ("router",)

logger = get_logger("entrypoints.admin_runtime_metrics")

_ADMIN_GUARD = Depends(require_admin((AdminRole.OPERATOR, AdminRole.SUPER_ADMIN)))

router = APIRouter(dependencies=[_ADMIN_GUARD])


@router.get(
    "/pools/snapshot",
    summary="Метрики пулов соединений",
    description="idle/active/total по каждому зарегистрированному пулу.",
    tags=["Admin · Runtime"],
    responses={200: {"description": "Метрики пулов."}},
)
async def pools_snapshot() -> dict[str, dict[str, Any]]:
    """Метрики пулов соединений."""
    from src.backend.infrastructure.clients.unified_pool_manager import (
        get_unified_pool_manager,
    )

    return await get_unified_pool_manager().get_metrics()


@router.get(
    "/processes/active",
    summary="Активные процессы workflow",
    description="Инстансы workflow'а, готовые к обработке worker'ом.",
    tags=["Admin · Runtime"],
    responses={200: {"description": "Список активных инстансов."}},
)
async def processes_active(
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Инстансы workflow'а в очереди на обработку."""
    from src.backend.core.di.providers.workflow import get_workflow_state_store_provider

    store = get_workflow_state_store_provider()
    rows = await store.list_pending(limit=limit)
    return [
        {
            "id": str(row.id),
            "workflow_name": row.workflow_name,
            "route_id": row.route_id,
            "status": str(row.status),
            "tenant_id": row.tenant_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.get(
    "/processes/stats",
    summary="Статистика процессов workflow",
    description="Количество инстансов workflow'а по статусам.",
    tags=["Admin · Runtime"],
    responses={200: {"description": "Счётчики по статусам."}},
)
async def processes_stats() -> dict[str, int]:
    """Количество инстансов workflow'а по статусам."""
    from src.backend.core.di.providers.workflow import get_workflow_state_store_provider

    store = get_workflow_state_store_provider()
    return await store.count_by_status()
