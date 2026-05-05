"""Admin endpoints для management-операций над ConnectorRegistry.

IL1.7 (ADR-022): manual reload клиента без рестарта приложения.
W26.5: маршруты регистрируются декларативно через ActionSpec; вся
логика per-endpoint вынесена в локальный ``_AdminConnectorsFacade``.

Endpoints (под /admin):
  * GET    /connectors                       — список + health (fast).
  * POST   /connectors/{name}/reload         — drain → rebuild → swap.
  * GET    /connectors/{name}/config         — хранимый Mongo-конфиг.
  * PUT    /connectors/{name}/config         — upsert + best-effort reload.
  * DELETE /connectors/{name}/config         — удалить хранимый конфиг.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.backend.entrypoints.api.generator.actions import (
    ActionRouterBuilder,
    ActionSpec,
)

__all__ = ("router",)


# --- Schemas ---------------------------------------------------------------


class ConnectorNamePath(BaseModel):
    """Path-параметр имени коннектора."""

    name: str = Field(..., description="Имя зарегистрированного коннектора.")


class ConnectorConfigPayload(BaseModel):
    """Тело запроса PUT /connectors/{name}/config."""

    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    user: str | None = None


# --- Service facade --------------------------------------------------------


class _AdminConnectorsFacade:
    """Адаптер над ``ConnectorRegistry`` + ``ConnectorConfigStore``.

    Лениво импортирует обе зависимости — это позволяет файлу загружаться
    в усечённой dev_light-сборке, где Mongo/Registry могут отсутствовать.
    """

    async def list_connectors(self) -> dict[str, Any]:
        # Wave 6.5a: registry резолвится через core.di.providers (lazy).
        try:
            from src.backend.core.di.providers import get_connector_registry_provider

            registry = get_connector_registry_provider()
        except ImportError as exc:
            raise HTTPException(
                status_code=503, detail=f"registry unavailable: {exc}"
            ) from exc

        names = registry.names()
        health = await registry.health_all(mode="fast") if names else {}

        connectors: list[dict[str, Any]] = []
        for connector_name in names:
            r = health.get(connector_name)
            connectors.append(
                {
                    "name": connector_name,
                    "vault_path": registry.vault_path(connector_name),
                    "health": (
                        {
                            "status": r.status,
                            "latency_ms": r.latency_ms,
                            "error": r.error,
                        }
                        if r
                        else None
                    ),
                }
            )
        return {"total": len(connectors), "connectors": connectors}

    async def reload_connector(self, *, name: str) -> dict[str, Any]:
        # Wave 6.5a: registry + error class — через DI providers.
        try:
            from src.backend.core.di.providers import (
                get_connector_registry_errors_provider,
                get_connector_registry_provider,
            )

            registry = get_connector_registry_provider()
            ConnectorNotRegisteredError = get_connector_registry_errors_provider()
        except ImportError as exc:
            raise HTTPException(
                status_code=503, detail=f"Registry unavailable: {exc}"
            ) from exc

        start = time.perf_counter()
        try:
            duration_ms = await registry.reload(name)
        except ConnectorNotRegisteredError:
            raise HTTPException(
                status_code=404, detail=f"Connector '{name}' not registered"
            ) from None
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=500, detail=f"Reload failed: {type(exc).__name__}: {exc}"
            ) from exc

        try:
            client = registry.get(name)
            post_health = await client.health(mode="fast")
            post_status = post_health.status
            post_error = post_health.error
        except Exception as exc:  # noqa: BLE001
            post_status = "unknown"
            post_error = str(exc)[:200]

        total_ms = (time.perf_counter() - start) * 1000.0
        return {
            "name": name,
            "reload_duration_ms": round(duration_ms, 2),
            "total_duration_ms": round(total_ms, 2),
            "post_reload_health": {"status": post_status, "error": post_error},
        }

    async def get_config(self, *, name: str) -> dict[str, Any]:
        store = _resolve_config_store_or_503()
        entry = await store.get(name)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"No config for {name!r}")
        return entry.model_dump(mode="json")

    async def put_config(
        self,
        *,
        name: str,
        config: dict[str, Any],
        enabled: bool = True,
        user: str | None = None,
    ) -> dict[str, Any]:
        store = _resolve_config_store_or_503()
        entry = await store.save(name, config, enabled=enabled, user=user)

        reload_status: dict[str, Any] = {"attempted": False}
        try:
            # Wave 6.5a: registry + error class — через DI providers.
            from src.backend.core.di.providers import (
                get_connector_registry_errors_provider,
                get_connector_registry_provider,
            )

            registry = get_connector_registry_provider()
            ConnectorNotRegisteredError = get_connector_registry_errors_provider()
            reload_status["attempted"] = True
            try:
                duration_ms = await registry.reload(name)
                reload_status["duration_ms"] = round(duration_ms, 2)
                reload_status["status"] = "ok"
            except ConnectorNotRegisteredError:
                reload_status["status"] = "not_registered"
            except Exception as reload_exc:  # noqa: BLE001
                reload_status["status"] = "failed"
                reload_status["error"] = str(reload_exc)[:200]
        except ImportError:
            reload_status["status"] = "registry_unavailable"

        return {"saved": entry.model_dump(mode="json"), "reload": reload_status}

    async def delete_config(self, *, name: str) -> dict[str, bool]:
        store = _resolve_config_store_or_503()
        deleted = await store.delete(name)
        return {"deleted": deleted}


def _resolve_config_store_or_503() -> Any:
    """Lazy резолв ``ConnectorConfigStore`` через DI provider или 503.

    Wave 6.5a: вместо прямого импорта ``infrastructure.repositories...``
    используется ``core.di.providers.get_connector_config_store_provider``
    (paттерн W6.4 — provider уже существует).
    """
    try:
        from src.backend.core.di.providers import get_connector_config_store_provider

        return get_connector_config_store_provider()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"ConnectorConfigStore unavailable: {exc}"
        ) from exc


_FACADE = _AdminConnectorsFacade()


def _get_facade() -> _AdminConnectorsFacade:
    return _FACADE


# --- Router ----------------------------------------------------------------


router = APIRouter(tags=["Admin · Infrastructure"])
builder = ActionRouterBuilder(router)

common_tags = ("Admin · Infrastructure",)


builder.add_actions(
    [
        ActionSpec(
            name="admin_list_connectors",
            method="GET",
            path="/connectors",
            summary="Список зарегистрированных infra-клиентов",
            service_getter=_get_facade,
            service_method="list_connectors",
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_reload_connector",
            method="POST",
            path="/connectors/{name}/reload",
            summary="Manual reload одного infra-клиента (drain → rebuild → swap)",
            status_code=status.HTTP_202_ACCEPTED,
            service_getter=_get_facade,
            service_method="reload_connector",
            path_model=ConnectorNamePath,
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_get_connector_config",
            method="GET",
            path="/connectors/{name}/config",
            summary="Получить хранимый конфиг коннектора",
            service_getter=_get_facade,
            service_method="get_config",
            path_model=ConnectorNamePath,
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_put_connector_config",
            method="PUT",
            path="/connectors/{name}/config",
            summary="Сохранить конфиг коннектора (upsert) + reload",
            service_getter=_get_facade,
            service_method="put_config",
            path_model=ConnectorNamePath,
            body_model=ConnectorConfigPayload,
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_delete_connector_config",
            method="DELETE",
            path="/connectors/{name}/config",
            summary="Удалить хранимый конфиг коннектора",
            service_getter=_get_facade,
            service_method="delete_config",
            path_model=ConnectorNamePath,
            tags=common_tags,
        ),
    ]
)
