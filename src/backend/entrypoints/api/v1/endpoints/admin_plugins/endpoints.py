from __future__ import annotations

"""S62 W1 — endpoints.py part of admin_plugins decomp.

Funcs: list_plugins, get_plugin_manifest, toggle_plugin, list_plugin_versions, diff_plugin_versions, rollback_plugin, get_dependency_graph, scaffold_plugin_endpoint.

8 endpoint funcs (list, get, toggle, versions, diff, rollback, graph, scaffold).
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status

from src.backend.entrypoints.api.v1.endpoints.admin_plugins import helpers
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.schemas import (
    PluginDependencyGraph,
    PluginDiffResponse,
    PluginManifest,
    PluginRollbackRequest,
    PluginRollbackResponse,
    PluginScaffoldRequest,
    PluginScaffoldResponse,
    PluginSummary,
    PluginToggleRequest,
    PluginToggleResponse,
    PluginVersionsResponse,
)  # S62 W1: schemas

router = APIRouter(prefix="/admin/plugins", tags=["admin"])

_check_flag_enabled = helpers._check_flag_enabled
_get_plugin_registry = helpers._get_plugin_registry
_get_version_service = helpers._get_version_service
_mock_manifest = helpers._mock_manifest
_mock_plugins = helpers._mock_plugins
logger = helpers.logger

# ─── Pydantic-схемы запроса/ответа ────────────────────────────────────────────


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


async def list_plugin_versions(name: str) -> PluginVersionsResponse:
    """Перечислить все локально установленные версии плагина."""
    _check_flag_enabled()
    service = _get_version_service()
    if service is None:
        return PluginVersionsResponse(plugin=name, versions=[])
    versions = service.list_versions(name)
    return PluginVersionsResponse(plugin=name, versions=[v.to_dict() for v in versions])


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
