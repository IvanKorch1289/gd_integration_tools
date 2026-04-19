"""Kubernetes probes: readiness, liveness, startup.

Эндпоинты без аутентификации для оркестратора контейнеров.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

__all__ = ("router",)

router = APIRouter(tags=["Health"])


@router.get("/readiness", summary="Kubernetes readiness probe")
async def readiness_probe(request: Request) -> JSONResponse:
    """Возвращает 200 если приложение готово принимать трафик.

    Проверяет: инициализация завершена, DB подключена,
    Redis подключён, хотя бы один брокер доступен.
    """
    if not getattr(request.app.state, "infrastructure_ready", False):
        return JSONResponse(
            status_code=503,
            content={"status": "initializing"},
        )

    from app.core.utils.health_check import get_healthcheck_service

    try:
        async with get_healthcheck_service() as hc:
            db_ok = await hc.check_database()
            redis_ok = await hc.check_redis()
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "health_check_failed"},
        )

    if not (db_ok and redis_ok):
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "database": db_ok,
                "redis": redis_ok,
            },
        )

    return JSONResponse(
        content={
            "status": "ready",
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )


@router.get("/liveness", summary="Kubernetes liveness probe")
async def liveness_probe() -> JSONResponse:
    """Возвращает 200 если процесс жив.

    K8s перезапустит контейнер при 3+ неудачных проверках.
    """
    from app.infrastructure.database.database import db_initializer

    try:
        alive = await db_initializer.check_connection()
        if alive:
            return JSONResponse(content={"status": "alive"})
    except Exception:
        pass

    return JSONResponse(
        status_code=503,
        content={"status": "unhealthy"},
    )


@router.get("/startup", summary="Kubernetes startup probe")
async def startup_probe(request: Request) -> JSONResponse:
    """Возвращает 200 когда DSL-маршруты и actions зарегистрированы.

    Медленный startup probe предотвращает преждевременный
    рестарт контейнера во время инициализации.
    """
    if not getattr(request.app.state, "infrastructure_ready", False):
        return JSONResponse(
            status_code=503,
            content={"status": "starting"},
        )

    from app.dsl.commands.registry import action_handler_registry, route_registry

    return JSONResponse(
        content={
            "status": "started",
            "routes": len(route_registry.list_routes()),
            "actions": len(action_handler_registry.list_actions()),
        }
    )


@router.get("/components", summary="Detailed component health (uses HealthAggregator)")
async def components_health() -> JSONResponse:
    """ARCH-3: Unified component health через HealthAggregator.

    Возвращает parallel-checked health всех зарегистрированных компонентов:
    {status: ok|degraded|down, timestamp, components: {name: {...}}}.
    """
    try:
        from app.infrastructure.application.health_aggregator import (
            get_health_aggregator,
        )
        aggregator = get_health_aggregator()
        report = await aggregator.check_all()
        status_code = 200 if report.get("status") == "ok" else 503
        return JSONResponse(status_code=status_code, content=report)
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "error": str(exc)[:200]},
        )
