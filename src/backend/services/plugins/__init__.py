"""Wave 4 (Roadmap V10) — composition root для plugin-системы.

Слой `services/plugins/` склеивает `core/interfaces/plugin.py` (контракт)
с конкретными реестрами actions/processors/repository-hooks и
обнаружением плагинов через `importlib.metadata.entry_points`.

Публичные точки входа:

* :class:`PluginLoader` — orchestrator (discovery + lifecycle).
* :class:`RepositoryHookRegistry` — централизованный реестр hooks/override.
* :func:`repository_hook` / :func:`override_method` — декораторы.
* :class:`PluginManifest` — pydantic-схема `plugin.yaml`.
"""

from __future__ import annotations

from src.backend.services.plugins.decorators import override_method, repository_hook
from src.backend.services.plugins.loader import PluginLoader, get_plugin_loader
from src.backend.services.plugins.manifest_toml import (  # S168 W15-17: yaml manifest.py superseded
    PluginManifest,
    load_plugin_manifest,  # was load_manifest in old yaml manifest.py
)
# Backward-compat alias (S168 W15-17 deprecation shim)
load_manifest = load_plugin_manifest
from src.backend.services.plugins.registries import (
    ActionRegistryAdapter,
    ProcessorRegistryAdapter,
    RepositoryHookRegistry,
    get_repository_hook_registry,
)

__all__ = (
    "ActionRegistryAdapter",
    "PluginLoader",
    "PluginManifest",
    "ProcessorRegistryAdapter",
    "RepositoryHookRegistry",
    "get_plugin_loader",
    "get_repository_hook_registry",
    "load_manifest",
    "override_method",
    "repository_hook",
)
