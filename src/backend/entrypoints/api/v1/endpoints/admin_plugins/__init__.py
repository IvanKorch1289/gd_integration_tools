"""Admin plugins API endpoints (S62 W1 decomp from admin_plugins.py 514 LOC).

11 schemas + 13 funcs decomposed в 3 files:
- ``schemas.py``: 11 Pydantic schemas
- ``helpers.py``: 5 helpers
- ``endpoints.py``: 8 endpoint funcs

Backward-compat: ``from src.backend.entrypoints.api.v1.endpoints.admin_plugins import PluginSummary`` works.
"""

from __future__ import annotations

from src.backend.entrypoints.api.v1.endpoints.admin_plugins.endpoints import (
    diff_plugin_versions,  # S62 W1: re-export
    get_dependency_graph,  # S62 W1: re-export
    get_plugin_manifest,  # S62 W1: re-export
    list_plugin_versions,  # S62 W1: re-export
    list_plugins,  # S62 W1: re-export
    rollback_plugin,  # S62 W1: re-export
    scaffold_plugin_endpoint,  # S62 W1: re-export
    toggle_plugin,  # S62 W1: re-export
)
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.helpers import (
    _check_flag_enabled,  # S62 W1: re-export
    _get_plugin_registry,  # S62 W1: re-export
    _get_version_service,  # S62 W1: re-export
    _mock_manifest,  # S62 W1: re-export
    _mock_plugins,  # S62 W1: re-export
)
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.schemas import (
    PluginDependencyGraph,  # S62 W1: re-export
    PluginDiffResponse,  # S62 W1: re-export
    PluginManifest,  # S62 W1: re-export
    PluginRollbackRequest,  # S62 W1: re-export
    PluginRollbackResponse,  # S62 W1: re-export
    PluginScaffoldRequest,  # S62 W1: re-export
    PluginScaffoldResponse,  # S62 W1: re-export
    PluginSummary,  # S62 W1: re-export
    PluginToggleRequest,  # S62 W1: re-export
    PluginToggleResponse,  # S62 W1: re-export
    PluginVersionsResponse,  # S62 W1: re-export
)

__all__ = (
    "PluginSummary",
    "PluginManifest",
    "PluginToggleRequest",
    "PluginToggleResponse",
    "PluginVersionsResponse",
    "PluginDiffResponse",
    "PluginRollbackRequest",
    "PluginRollbackResponse",
    "PluginDependencyGraph",
    "PluginScaffoldRequest",
    "PluginScaffoldResponse",
    "_check_flag_enabled",
    "_get_plugin_registry",
    "_mock_plugins",
    "_mock_manifest",
    "list_plugins",
    "get_plugin_manifest",
    "toggle_plugin",
    "_get_version_service",
    "list_plugin_versions",
    "diff_plugin_versions",
    "rollback_plugin",
    "get_dependency_graph",
    "scaffold_plugin_endpoint",
)
