"""Structural protocol for LoadingMixin/FrontendMixin/LoaderMixin.

Breaks the circular dependency between ``PluginLoaderV11`` and the loading
mixins and gives mypy enough information about the private attributes/helpers
the mixins use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from src.backend.core.interfaces.plugin import BasePlugin
from src.backend.services.plugins.loader_v11.discovery import LoadedPluginV11
from src.backend.services.plugins.manifest_v11 import PluginManifestV11


class _LoadingProtocol(Protocol):
    """Common shape expected by plugin loading mixins."""

    _extensions_dir: Path
    _gate: Any
    _actions: Any
    _repos: Any
    _processors: Any
    _core_version: str
    _streamlit_pages_dir: Path | None
    _loaded: dict[str, LoadedPluginV11]
    _owners: dict[str, dict[str, str]]
    _loaded_failed: list[LoadedPluginV11]
    _loaded_skipped: list[LoadedPluginV11]

    def _check_inventory_collisions(self, manifest: PluginManifestV11) -> None: ...

    def _record_owners(self, manifest: PluginManifestV11) -> None: ...

    def _plugin_page_prefix(self, plugin_name: str) -> str: ...

    def _mount_frontend_pages(self, plugin_name: str, plugin_root: Path) -> int: ...

    def _unmount_frontend_pages(self, plugin_name: str) -> int: ...

    def _instantiate(self, manifest: PluginManifestV11) -> BasePlugin: ...
