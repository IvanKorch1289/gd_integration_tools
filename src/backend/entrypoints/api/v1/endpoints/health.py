"""Kubernetes probes: liveness, readiness, startup, components (W26.2).

Эндпоинты без аутентификации для оркестратора контейнеров.

Семантика по правилам W26 (см. ADR-036):

* ``/liveness`` — process-only. 200 пока процесс жив. Не вызывает БД,
  Redis или иные внешние зависимости — иначе K8s рестартит контейнер
  при кратковременных сбоях инфраструктуры.
* ``/readiness`` — 200 пока сервис может обрабатывать трафик, **в т.ч.
  через fallback'и**. При активном fallback в payload пишется
  ``"degraded": true`` с перечислением деградировавших компонентов;
  503 — только когда работа невозможна (все backend'ы upstream-цепочки
  отказали).
* ``/startup`` — 200 когда DSL-маршруты и actions зарегистрированы.
* ``/components?mode=fast|deep`` — детальный отчёт через
  ``HealthAggregator``. ``deep`` дополнительно включает per-chain
  состояние из ``ResilienceCoordinator``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

__all__ = ("router",)

router = APIRouter(tags=["Health"])


def _no_store_headers() -> dict[str, str]:
    """``Cache-Control: no-store`` для пробников — обходит LB-кэш."""
    return {"Cache-Control": "no-store"}


@router.get("/liveness", summary="Kubernetes liveness probe (process-only)")
async def liveness_probe() -> JSONResponse:
    """Возвращает 200 пока процесс жив. Не зависит от внешней инфры.

    K8s перезапускает контейнер при N подряд неудачных проверках.
    Liveness не должна падать при сбоях DB/Redis: иначе под уйдёт в
    crashloop, хотя fallback мог бы сохранить функциональность.
    """
    return JSONResponse(
        content={"status": "alive", "timestamp": datetime.now(UTC).isoformat()},
        headers=_no_store_headers(),
    )


@router.get(
    "/readiness", summary="Kubernetes readiness probe (graceful degradation aware)"
)
async def readiness_probe(request: Request) -> JSONResponse:
    """Возвращает 200 при работающем сервисе, в т.ч. через fallback'и.

    Логика:

    * не запущена ``infrastructure_ready`` → 503 ``initializing``;
    * любой компонент с ``status='error'`` (CB OPEN и fallback тоже упал
      или нет fallback chain) → 503 ``not_ready`` с перечнем;
    * хотя бы один компонент с ``status='degraded'`` → 200 ``degraded``
      с перечнем (под остаётся в трафике K8s);
    * иначе → 200 ``ready``.
    """
    if not getattr(request.app.state, "infrastructure_ready", False):
        return JSONResponse(
            status_code=503,
            content={"status": "initializing"},
            headers=_no_store_headers(),
        )

    try:
        # Wave 6.5a: ResilienceCoordinator — через DI provider.
        from src.backend.core.di.providers import get_resilience_coordinator_provider

        statuses = get_resilience_coordinator_provider().status()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content={"status": "health_check_failed", "error": str(exc)[:200]},
            headers=_no_store_headers(),
        )

    down: list[str] = []
    degraded: list[str] = []
    for name, comp in statuses.items():
        if comp.degradation == "down":
            down.append(name)
        elif comp.degradation == "degraded":
            degraded.append(name)

    if down:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "degraded": bool(degraded),
                "down_components": sorted(down),
                "degraded_components": sorted(degraded),
                "timestamp": datetime.now(UTC).isoformat(),
            },
            headers=_no_store_headers(),
        )

    payload: dict[str, Any] = {
        "status": "ready",
        "degraded": bool(degraded),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if degraded:
        payload["degraded_components"] = sorted(degraded)
    return JSONResponse(content=payload, headers=_no_store_headers())


@router.get("/startup", summary="Kubernetes startup probe")
async def startup_probe(request: Request) -> JSONResponse:
    """Возвращает 200 когда DSL-маршруты и actions зарегистрированы.

    Медленный startup probe предотвращает преждевременный рестарт
    контейнера во время инициализации.
    """
    if not getattr(request.app.state, "infrastructure_ready", False):
        return JSONResponse(
            status_code=503, content={"status": "starting"}, headers=_no_store_headers()
        )

    from src.backend.dsl.commands.registry import (
        action_handler_registry,
        route_registry,
    )

    return JSONResponse(
        content={
            "status": "started",
            "routes": len(route_registry.list_routes()),
            "actions": len(action_handler_registry.list_actions()),
        },
        headers=_no_store_headers(),
    )


@router.get("/components", summary="Detailed component health")
async def components_health(mode: str = "fast") -> JSONResponse:
    """Расширенный отчёт через ``HealthAggregator`` + ``ResilienceCoordinator``.

    Query-параметр ``mode``:

    * ``fast`` (default) — быстрый PING per-компонент, SLA <100ms.
    * ``deep`` — smoke-operation, SLA <2s, плюс per-chain статус
      из ``ResilienceCoordinator`` (breaker_state / chain /
      last_used_backend / degradation).

    Возвращает 200 при ``ok`` или ``degraded`` (т.к. деградация — не
    отказ); 503 при ``down``. Это согласуется с readiness-probe.
    """
    if mode not in ("fast", "deep"):
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "error": f"invalid mode: {mode!r} (use fast|deep)",
            },
            headers=_no_store_headers(),
        )

    try:
        # Wave 6.5a: health_aggregator + resilience_components_report —
        # через DI providers (lazy importlib).
        from src.backend.core.di.providers import (
            get_health_aggregator_provider,
            get_resilience_components_report_provider,
        )

        aggregator = get_health_aggregator_provider()
        report = await aggregator.check_all(mode=mode)  # type: ignore[arg-type]

        # Для deep-режима добавляем подробный per-chain отчёт.
        if mode == "deep":
            resilience_components_report = get_resilience_components_report_provider()
            report["resilience_chains"] = resilience_components_report()

        overall = report.get("status", "ok")
        status_code = 503 if overall == "down" else 200
        return JSONResponse(
            status_code=status_code, content=report, headers=_no_store_headers()
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content={"status": "error", "error": str(exc)[:200]},
            headers=_no_store_headers(),
        )
