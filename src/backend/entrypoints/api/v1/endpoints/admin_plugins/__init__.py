from __future__ import annotations
"""Admin plugins API endpoints (S62 W1 decomp from admin_plugins.py 514 LOC).

11 schemas + 13 funcs decomposed в 3 files:
- ``schemas.py``: 11 Pydantic schemas
- ``helpers.py``: 5 helpers
- ``endpoints.py``: 8 endpoint funcs

Backward-compat: ``from src.backend.entrypoints.api.v1.endpoints.admin_plugins import PluginSummary`` works.
"""


from src.backend.entrypoints.api.v1.endpoints.admin_plugins.schemas import PluginSummary  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.schemas import PluginManifest  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.schemas import PluginToggleRequest  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.schemas import PluginToggleResponse  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.schemas import PluginVersionsResponse  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.schemas import PluginDiffResponse  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.schemas import PluginRollbackRequest  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.schemas import PluginRollbackResponse  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.schemas import PluginDependencyGraph  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.schemas import PluginScaffoldRequest  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.schemas import PluginScaffoldResponse  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.helpers import _check_flag_enabled  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.helpers import _get_plugin_registry  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.helpers import _mock_plugins  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.helpers import _mock_manifest  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.helpers import _get_version_service  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.endpoints import list_plugins  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.endpoints import get_plugin_manifest  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.endpoints import toggle_plugin  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.endpoints import list_plugin_versions  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.endpoints import diff_plugin_versions  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.endpoints import rollback_plugin  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.endpoints import get_dependency_graph  # S62 W1: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_plugins.endpoints import scaffold_plugin_endpoint  # S62 W1: re-export

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
