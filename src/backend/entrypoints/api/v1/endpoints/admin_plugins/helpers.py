"""S62 W1 — helpers.py part of admin_plugins decomp.

Funcs: _check_flag_enabled, _get_plugin_registry, _mock_plugins, _mock_manifest, _get_version_service.

5 helpers (flag check, registry, mock data, version service).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from src.backend.entrypoints.api.v1.endpoints.admin_plugins.schemas import (
    PluginManifest,
    PluginSummary,
)
from src.backend.core.logging import get_logger

logger = get_logger(__name__)


# ─── Pydantic-схемы запроса/ответа ────────────────────────────────────────────


def _check_flag_enabled() -> None:
    """Проверяет feature-flag admin_marketplace_endpoints.

    Вызывает HTTP 503, если флаг выключен (default-OFF).
    """
    from src.backend.core.feature_flags import get_feature_flag_service  # lazy import

    if not get_feature_flag_service().is_enabled("admin_marketplace_endpoints"):
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


def _get_version_service() -> Any | None:
    """Получить :class:`PluginVersionService` из app.state, если есть.

    Lazy-import чтобы не тянуть infrastructure при сборке schema.
    """
    try:
        from src.backend.main import app as fastapi_app

        loader = getattr(fastapi_app.state, "plugin_loader_v1", None)
        if loader is None:
            return None
        from src.backend.services.plugins.versioning import PluginVersionService

        return PluginVersionService(loader=loader, extensions_dir=Path("extensions"))
    except Exception as _:
        return None
