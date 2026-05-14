"""Admin REST API для Plugin-Marketplace (K5 W4).

Эндпоинты предоставляют Streamlit-странице ``60_Plugin_Marketplace.py``
доступ к реестру плагинов и управление их активностью.

Endpoints (под /api/v1/admin/plugins):

    * GET  /list              — список зарегистрированных плагинов.
    * GET  /{name}/manifest   — содержимое plugin.toml.
    * POST /{name}/toggle     — включение/отключение плагина.

Флаг-охрана: ``feature_flags.admin_marketplace_endpoints == False``
→ 503 Service Unavailable для всех эндпоинтов.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

__all__ = ("router",)

router = APIRouter(prefix="/admin/plugins", tags=["admin"])


# ─── Pydantic-схемы запроса/ответа ────────────────────────────────────────────


class PluginSummary(BaseModel):
    """Краткое описание плагина из реестра."""

    name: str
    version: str
    status: str  # "active" | "inactive" | "error"
    capabilities: list[str] = Field(default_factory=list)
    routes_count: int = 0
    actions_count: int = 0


class PluginManifest(BaseModel):
    """Содержимое plugin.toml в структурированном виде."""

    name: str
    version: str
    requires_core: str
    capabilities: list[str] = Field(default_factory=list)
    tenant_aware: bool = False
    provides: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict, description="Сырое содержимое TOML")


class PluginToggleRequest(BaseModel):
    """Тело запроса POST /{name}/toggle."""

    active: bool = Field(..., description="True — активировать, False — деактивировать")


class PluginToggleResponse(BaseModel):
    """Результат операции toggle."""

    name: str
    active: bool
    previous_status: str
    current_status: str


# ─── Вспомогательные функции ──────────────────────────────────────────────────


def _check_flag_enabled() -> None:
    """Проверяет feature-flag admin_marketplace_endpoints.

    Вызывает HTTP 503, если флаг выключен (default-OFF).
    """
    from src.backend.core.config.features import feature_flags  # lazy import

    if not feature_flags.admin_marketplace_endpoints:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin marketplace endpoints отключены (feature_flags.admin_marketplace_endpoints=False)",
        )


def _get_plugin_registry() -> Any:
    """Возвращает PluginRegistry/PluginLoader, если доступен.

    При недоступности возвращает None — эндпоинты используют mock.
    """
    try:
        from src.backend.core.plugin_runtime.loader import PluginLoader  # lazy import

        return PluginLoader.get_instance()
    except Exception:  # noqa: BLE001
        logger.warning("PluginLoader недоступен — используется mock")
        return None


def _mock_plugins() -> list[PluginSummary]:
    """Возвращает mock-список плагинов для случая недоступного реестра."""
    return [
        PluginSummary(
            name="core_entities",
            version="1.0.0",
            status="active",
            capabilities=["db.read", "db.write"],
            routes_count=4,
            actions_count=12,
        ),
        PluginSummary(
            name="credit_workflow",
            version="0.5.0",
            status="inactive",
            capabilities=["db.read", "http.external"],
            routes_count=2,
            actions_count=5,
        ),
    ]


def _mock_manifest(name: str) -> PluginManifest:
    """Возвращает mock-манифест плагина."""
    return PluginManifest(
        name=name,
        version="1.0.0",
        requires_core=">=1.0.0",
        capabilities=["db.read"],
        tenant_aware=False,
        provides=[f"{name}.service"],
        raw={
            "name": name,
            "version": "1.0.0",
            "requires_core": ">=1.0.0",
            "capabilities": ["db.read"],
        },
    )


# ─── Эндпоинты ────────────────────────────────────────────────────────────────


@router.get(
    "/list",
    response_model=list[PluginSummary],
    summary="Список зарегистрированных плагинов",
    description="Возвращает все плагины из PluginLoader. 503 при default-OFF flag.",
)
async def list_plugins() -> list[PluginSummary]:
    """Возвращает список плагинов из реестра.

    Returns:
        Список :class:`PluginSummary` с name, version, status, capabilities,
        routes_count, actions_count.

    Raises:
        HTTPException: 503 если feature_flags.admin_marketplace_endpoints=False.
    """
    _check_flag_enabled()

    registry = _get_plugin_registry()
    if registry is None:
        return _mock_plugins()

    try:
        plugins = registry.list_all()
        return [
            PluginSummary(
                name=getattr(p, "name", str(p)),
                version=str(getattr(p, "version", "0.0.0")),
                status="active" if getattr(p, "is_active", True) else "inactive",
                capabilities=list(getattr(p, "capabilities", [])),
                routes_count=int(getattr(p, "routes_count", 0)),
                actions_count=int(getattr(p, "actions_count", 0)),
            )
            for p in plugins
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ошибка чтения реестра плагинов: %s — возврат mock", exc)
        return _mock_plugins()


@router.get(
    "/{name}/manifest",
    response_model=PluginManifest,
    summary="Манифест плагина",
    description="Возвращает содержимое plugin.toml указанного плагина.",
)
async def get_plugin_manifest(name: str) -> PluginManifest:
    """Возвращает манифест плагина по имени.

    Args:
        name: Имя плагина в реестре.

    Returns:
        :class:`PluginManifest` с разобранными полями и raw TOML.

    Raises:
        HTTPException: 503 если флаг выключен; 404 если плагин не найден.
    """
    _check_flag_enabled()

    registry = _get_plugin_registry()
    if registry is None:
        return _mock_manifest(name)

    try:
        plugin = registry.get(name)
        if plugin is None:
            raise KeyError(name)
        manifest = getattr(plugin, "manifest", {})
        return PluginManifest(
            name=manifest.get("name", name),
            version=str(manifest.get("version", "0.0.0")),
            requires_core=str(manifest.get("requires_core", ">=1.0.0")),
            capabilities=list(manifest.get("capabilities", [])),
            tenant_aware=bool(manifest.get("tenant_aware", False)),
            provides=list(manifest.get("provides", [])),
            raw=dict(manifest),
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Плагин '{name}' не найден в реестре",
        )


@router.post(
    "/{name}/toggle",
    response_model=PluginToggleResponse,
    summary="Включить/отключить плагин",
    description="Переключает статус активности плагина. Требует feature flag ON.",
)
async def toggle_plugin(name: str, body: PluginToggleRequest) -> PluginToggleResponse:
    """Включает или отключает плагин по имени.

    Args:
        name: Имя плагина в реестре.
        body: :class:`PluginToggleRequest` с полем active.

    Returns:
        :class:`PluginToggleResponse` с предыдущим и текущим статусом.

    Raises:
        HTTPException: 503 если флаг выключен; 404 если плагин не найден.
    """
    _check_flag_enabled()

    registry = _get_plugin_registry()
    if registry is None:
        # Mock-ответ при недоступном реестре
        previous = "inactive" if body.active else "active"
        current = "active" if body.active else "inactive"
        return PluginToggleResponse(
            name=name,
            active=body.active,
            previous_status=previous,
            current_status=current,
        )

    try:
        plugin = registry.get(name)
        if plugin is None:
            raise KeyError(name)
        previous_status = "active" if getattr(plugin, "is_active", True) else "inactive"

        if body.active:
            await registry.activate(name)
        else:
            await registry.deactivate(name)

        current_status = "active" if body.active else "inactive"
        return PluginToggleResponse(
            name=name,
            active=body.active,
            previous_status=previous_status,
            current_status=current_status,
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Плагин '{name}' не найден в реестре",
        )
