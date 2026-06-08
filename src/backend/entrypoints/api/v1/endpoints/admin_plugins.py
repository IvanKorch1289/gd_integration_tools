"""Admin REST API для Plugin-Marketplace (K5 W4 + Sprint 14 K5 W2/W3/W6).

Эндпоинты предоставляют Streamlit-странице ``60_Plugin_Marketplace.py``
доступ к реестру плагинов и управление их активностью.

Endpoints (под /api/v1/admin/plugins):

    * GET  /list              — список зарегистрированных плагинов.
    * GET  /{name}/manifest   — содержимое plugin.toml.
    * POST /{name}/toggle     — включение/отключение плагина.
    * GET  /{name}/versions   — Sprint 14 K5 W2: установленные версии.
    * GET  /{name}/diff       — Sprint 14 K5 W2: diff двух версий.
    * POST /{name}/rollback   — Sprint 14 K5 W2: rollback на версию.
    * GET  /dependency-graph  — Sprint 14 K5 W3: граф зависимостей.
    * POST /scaffold          — Sprint 14 K5 W6: scaffold плагина.

Флаг-охрана: ``feature_flags.admin_marketplace_endpoints == False``
→ 503 Service Unavailable для всех эндпоинтов.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.backend.infrastructure.logging.factory import get_logger

logger = get_logger(__name__)

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
    raw: dict[str, Any] = Field(
        default_factory=dict, description="Сырое содержимое TOML"
    )


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
        from src.backend.core.plugin_runtime.loader import PluginLoader  # type: ignore[import-not-found]  # noqa: I001  # lazy import

        return PluginLoader.get_instance()
    except Exception as _:
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
    except Exception as exc:
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


# ─── Sprint 14 K5 W2: versioning + rollback ───────────────────────────────────


class PluginVersionsResponse(BaseModel):
    """Список локально установленных версий плагина."""

    plugin: str
    versions: list[dict[str, Any]]


class PluginDiffResponse(BaseModel):
    """Diff двух версий плагина (см. MigrationDiffer)."""

    plugin: str
    from_version: str
    to_version: str
    payload: dict[str, Any]


class PluginRollbackRequest(BaseModel):
    """Тело запроса POST /{name}/rollback."""

    to_version: str = Field(..., description="Целевая версия (SemVer).")


class PluginRollbackResponse(BaseModel):
    """Результат rollback-операции."""

    plugin: str
    from_version: str
    to_version: str
    status: str
    reason: str | None = None


def _get_version_service() -> Any | None:
    """Получить :class:`PluginVersionService` из app.state, если есть.

    Lazy-import чтобы не тянуть infrastructure при сборке schema.
    """
    try:
        from src.backend.main import app as fastapi_app

        loader = getattr(fastapi_app.state, "plugin_loader_v11", None)
        if loader is None:
            return None
        from src.backend.services.plugins.versioning import PluginVersionService

        return PluginVersionService(loader=loader, extensions_dir=Path("extensions"))
    except Exception as _:
        return None


@router.get(
    "/{name}/versions",
    response_model=PluginVersionsResponse,
    summary="Sprint 14 K5 W2: установленные версии плагина",
)
async def list_plugin_versions(name: str) -> PluginVersionsResponse:
    """Перечислить все локально установленные версии плагина."""
    _check_flag_enabled()
    service = _get_version_service()
    if service is None:
        return PluginVersionsResponse(plugin=name, versions=[])
    versions = service.list_versions(name)
    return PluginVersionsResponse(plugin=name, versions=[v.to_dict() for v in versions])


@router.get(
    "/{name}/diff",
    response_model=PluginDiffResponse,
    summary="Sprint 14 K5 W2: diff между двумя версиями",
)
async def diff_plugin_versions(
    name: str, from_version: str, to_version: str
) -> PluginDiffResponse:
    """Diff manifest'ов между ``from_version`` и ``to_version``."""
    _check_flag_enabled()
    service = _get_version_service()
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PluginVersionService недоступен (PluginLoaderV11 не запущен)",
        )
    try:
        result = service.diff(name, from_version=from_version, to_version=to_version)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return PluginDiffResponse(**result)


@router.post(
    "/{name}/rollback",
    response_model=PluginRollbackResponse,
    summary="Sprint 14 K5 W2: rollback плагина на конкретную версию",
)
async def rollback_plugin(
    name: str, body: PluginRollbackRequest
) -> PluginRollbackResponse:
    """Переключить активную версию плагина и выполнить hot-swap."""
    _check_flag_enabled()
    service = _get_version_service()
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PluginVersionService недоступен",
        )
    result = await service.rollback(name, to_version=body.to_version)
    return PluginRollbackResponse(**result.to_dict())


# ─── Sprint 14 K5 W3: dependency graph ────────────────────────────────────────


class PluginDependencyGraph(BaseModel):
    """Граф зависимостей плагинов (для Streamlit Mermaid визуализации)."""

    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, str]] = Field(default_factory=list)


@router.get(
    "/dependency-graph",
    response_model=PluginDependencyGraph,
    summary="Sprint 14 K5 W3: граф requires_plugins зависимостей",
)
async def get_dependency_graph() -> PluginDependencyGraph:
    """Собрать граф из ``plugin.toml::compatibility.requires_plugins``."""
    _check_flag_enabled()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    extensions_dir = Path("extensions")
    if not extensions_dir.is_dir():
        return PluginDependencyGraph()

    from src.backend.services.plugins.manifest_v11 import (
        PluginManifestError,
        load_plugin_manifest,
    )

    for child in sorted(extensions_dir.iterdir()):
        toml_path = child / "plugin.toml"
        if not toml_path.is_file():
            continue
        try:
            manifest = load_plugin_manifest(toml_path)
        except PluginManifestError:
            continue
        nodes.append(
            {
                "id": manifest.name,
                "version": manifest.version,
                "tenant_aware": manifest.tenant_aware,
            }
        )
        for required, spec in manifest.compatibility.requires_plugins.items():
            edges.append({"source": manifest.name, "target": required, "spec": spec})
    return PluginDependencyGraph(nodes=nodes, edges=edges)


# ─── Sprint 14 K5 W6: scaffold плагина ────────────────────────────────────────


class PluginScaffoldRequest(BaseModel):
    """Тело POST /plugins/scaffold."""

    name: str = Field(..., description="snake_case имя плагина", min_length=1)
    description: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    dry_run: bool = False


class PluginScaffoldResponse(BaseModel):
    """Результат scaffold-операции."""

    name: str
    created: bool
    path: str | None = None
    dry_run: bool = False
    actions: list[str] = Field(default_factory=list)


@router.post(
    "/scaffold",
    response_model=PluginScaffoldResponse,
    summary="Sprint 14 K5 W6: scaffold нового плагина",
)
async def scaffold_plugin_endpoint(
    body: PluginScaffoldRequest,
) -> PluginScaffoldResponse:
    """Создать каркас нового плагина (delegates ``tools.codegen_plugin``)."""
    _check_flag_enabled()
    if body.dry_run:
        return PluginScaffoldResponse(
            name=body.name,
            created=False,
            dry_run=True,
            actions=[
                f"would create extensions/{body.name}/plugin.toml",
                f"capabilities: {', '.join(body.capabilities) or '(none)'}",
                f"features: {', '.join(body.features) or '(none)'}",
            ],
        )
    try:
        from tools.codegen_plugin import scaffold_plugin

        plugin_root = scaffold_plugin(body.name)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return PluginScaffoldResponse(
        name=body.name,
        created=True,
        path=str(plugin_root),
        dry_run=False,
        actions=[f"created {plugin_root}"],
    )
