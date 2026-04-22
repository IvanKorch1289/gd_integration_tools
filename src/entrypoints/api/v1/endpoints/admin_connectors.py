"""Admin endpoints для management-операций над ConnectorRegistry.

IL1.7 (ADR-022): возможность manual reload клиента без рестарта приложения.
Используется on-call инженером (после Vault rotation fallback, подмены конфига
и т.п.) и внутренне — Vault refresher wiring в IL2.

Endpoints:
  * ``GET /admin/connectors`` — список зарегистрированных клиентов + health.
  * ``POST /admin/connectors/{name}/reload`` — drain → rebuild → swap.

Авторизация: reuse существующего admin-API-key механизма (на текущем уровне
развития проекта этот endpoint монтируется в /admin, который защищён
APIKeyMiddleware или аналогом; future-work — RBAC role `platform-admin`).

Rate-limit: endpoint `/reload` намеренно простой без rate-limit на уровне
кода — за ограничение отвечает upstream `APIKeyMiddleware` + audit-log.
При добавлении RBAC в IL2 можно повесить ``@RateLimit("5/minute/tenant")``.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

__all__ = ("router",)

router = APIRouter(tags=["Admin · Infrastructure"])


@router.get(
    "/connectors",
    summary="Список зарегистрированных infra-клиентов",
)
async def list_connectors() -> JSONResponse:
    """Вернуть состояние всех клиентов из ConnectorRegistry.

    Формат ответа::

        {
            "total": 4,
            "connectors": [
                {"name": "redis", "vault_path": "...", "health": {...}},
                ...
            ]
        }

    `health` собирается в режиме ``fast`` (быстрый PING). Для deep-probe
    используется `/health/components?mode=deep`.
    """
    try:
        from app.infrastructure.registry import ConnectorRegistry

        registry = ConnectorRegistry.instance()
    except ImportError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": f"registry unavailable: {exc}"},
        )

    names = registry.names()
    health = await registry.health_all(mode="fast") if names else {}

    connectors: list[dict[str, Any]] = []
    for name in names:
        r = health.get(name)
        connectors.append(
            {
                "name": name,
                "vault_path": registry.vault_path(name),
                "health": {
                    "status": r.status if r else "unknown",
                    "latency_ms": r.latency_ms if r else None,
                    "error": r.error if r else None,
                }
                if r
                else None,
            }
        )

    return JSONResponse(
        status_code=200,
        content={"total": len(connectors), "connectors": connectors},
    )


@router.post(
    "/connectors/{name}/reload",
    summary="Manual reload одного infra-клиента (drain → rebuild → swap)",
    status_code=status.HTTP_202_ACCEPTED,
)
async def reload_connector(name: str) -> JSONResponse:
    """Принудительный reload клиента через ConnectorRegistry.

    Поведение:

    1. Проверка, что клиент зарегистрирован (иначе 404).
    2. ``ConnectorRegistry.reload(name)`` — idempotent, защищён per-name lock-ом.
    3. Вернуть 202 с duration_ms и post-reload health.

    Используется для:

    * On-call manual recovery (пример: Redis повис → reload чтобы пересоздать pool).
    * Применения обновлённого конфига без рестарта.
    * (IL2) Vault-refresher callback при ротации секретов.
    """
    try:
        from app.infrastructure.registry import (
            ConnectorNotRegisteredError,
            ConnectorRegistry,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Registry unavailable: {exc}",
        ) from exc

    registry = ConnectorRegistry.instance()

    start = time.perf_counter()
    try:
        duration_ms = await registry.reload(name)
    except ConnectorNotRegisteredError:
        raise HTTPException(
            status_code=404,
            detail=f"Connector '{name}' not registered",
        ) from None
    except Exception as exc:  # noqa: BLE001
        # Reload мог упасть на стадии rebuild → клиент остался stopped.
        # Прокидываем 500 с подробностями; on-call увидит в audit-log.
        raise HTTPException(
            status_code=500,
            detail=f"Reload failed: {type(exc).__name__}: {exc}",
        ) from exc

    # Post-reload health — чтобы сразу видеть, взлетел ли клиент.
    try:
        client = registry.get(name)
        post_health = await client.health(mode="fast")
        post_status = post_health.status
        post_error = post_health.error
    except Exception as exc:  # noqa: BLE001
        post_status = "unknown"
        post_error = str(exc)[:200]

    total_ms = (time.perf_counter() - start) * 1000.0
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "name": name,
            "reload_duration_ms": round(duration_ms, 2),
            "total_duration_ms": round(total_ms, 2),
            "post_reload_health": {
                "status": post_status,
                "error": post_error,
            },
        },
    )
